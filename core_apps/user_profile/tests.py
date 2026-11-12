import base64
import tempfile
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, override_settings

from .models import Profile
from .serializers import ProfileSerializer
from .tasks import upload_photos_to_cloudinary


class ProfileSerializerTests(SimpleTestCase):
    def setUp(self):
        self.user = get_user_model()(
            email="profile@example.test", username="customer", last_name="Original",
        )
        self.profile = Profile(user=self.user)
        self.profile.save = Mock()
        self.user.save = Mock()

    def test_fields_match_models_and_user_sources(self):
        fields = ProfileSerializer().fields
        self.assertIn("view_count", fields)
        self.assertIn("account_currency", fields)
        self.assertIn("id_number", fields)
        self.assertEqual(fields["last_name"].source, "user.last_name")
        self.assertEqual(fields["date_joined"].source, "user.date_joined")

    def test_partial_update_without_user_fields(self):
        serializer = ProfileSerializer(self.profile, data={"city": "Lagos"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIs(serializer.save(), self.profile)
        self.assertEqual(self.profile.city, "Lagos")
        self.profile.save.assert_called_once()
        self.user.save.assert_not_called()

    def test_last_name_update_preserves_username(self):
        serializer = ProfileSerializer(self.profile, data={"last_name": "Updated"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(self.user.last_name, "Updated")
        self.assertEqual(self.user.username, "customer")

    @patch("core_apps.user_profile.serializers.transaction.on_commit")
    @patch("core_apps.user_profile.serializers.upload_photos_to_cloudinary.delay")
    def test_photo_only_update_queues_after_commit(self, delay, on_commit):
        photo = SimpleUploadedFile("photo.jpg", b"small image", content_type="image/jpeg")
        ProfileSerializer().update(self.profile, {"photo": photo})
        delay.assert_not_called()
        on_commit.assert_called_once()
        on_commit.call_args.args[0]()
        delay.assert_called_once_with(str(self.profile.id), {
            "photo": {"type": "base64", "data": base64.b64encode(b"small image").decode()},
        })

    @override_settings(MAX_UPLOAD_SIZE=1)
    @patch("core_apps.user_profile.serializers.transaction.on_commit")
    def test_large_photo_uses_storage_name(self, on_commit):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            photo = SimpleUploadedFile("photo.jpg", b"large image")
            ProfileSerializer().update(self.profile, {"photo": photo})
            payload = on_commit.call_args.args[0].args[1]["photo"]
            self.assertEqual(payload["type"], "file")
            with default_storage.open(payload["path"], "rb") as stored:
                self.assertEqual(stored.read(), b"large image")
            default_storage.delete(payload["path"])

    @patch("core_apps.user_profile.serializers.ProfileSerializer.get_view_count", return_value=0)
    @patch("core_apps.user_profile.models.Profile.next_of_kin")
    def test_profile_representation_includes_next_of_kin(self, relation, view_count):
        relation.all.return_value = []
        data = ProfileSerializer(self.profile).data
        self.assertEqual(data["next_of_kin"], [])
        self.assertEqual(data["last_name"], "Original")
        self.assertIn("date_joined", data)
        self.assertEqual(data["view_count"], 0)


class ProfileUploadTests(SimpleTestCase):
    @patch("core_apps.user_profile.tasks.apps.get_model")
    @patch("core_apps.user_profile.tasks.cloudinary.uploader.upload")
    def test_file_upload_reads_storage_path_and_saves_secure_url(self, upload, get_model):
        profile = get_model.return_value.objects.get.return_value
        upload.return_value = {"public_id": "profiles/photo", "secure_url": "https://example.test/photo.jpg"}
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            name = default_storage.save("temporary.jpg", SimpleUploadedFile("photo.jpg", b"image"))
            upload_photos_to_cloudinary.run("profile-id", {"photo": {"type": "file", "path": name}})
            upload.assert_called_once()
            self.assertFalse(default_storage.exists(name))
        self.assertEqual(profile.photo, "profiles/photo")
        self.assertEqual(profile.photo_url, "https://example.test/photo.jpg")
        profile.save.assert_called_once()

    @patch("core_apps.user_profile.tasks.apps.get_model")
    @patch("core_apps.user_profile.tasks.cloudinary.uploader.upload")
    def test_base64_upload(self, upload, get_model):
        upload.return_value = {"public_id": "profiles/id", "secure_url": "https://example.test/id.jpg"}
        upload_photos_to_cloudinary.run("profile-id", {
            "id_photo": {"type": "base64", "data": base64.b64encode(b"image").decode()},
        })
        upload.assert_called_once_with(b"image")
        self.assertEqual(get_model.return_value.objects.get.return_value.id_photo_url,
                         "https://example.test/id.jpg")
