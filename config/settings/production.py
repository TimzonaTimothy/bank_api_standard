from django.core.exceptions import ImproperlyConfigured

from .local import *

DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in getenv('ALLOWED_HOSTS', '').split(',') if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if origin.strip()]
if not SECRET_KEY or not ALLOWED_HOSTS or not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured('Production requires SECRET_KEY, ALLOWED_HOSTS and HTTPS CSRF_TRUSTED_ORIGINS.')
if '*' in ALLOWED_HOSTS or any(not origin.startswith('https://') for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured('Production requires explicit hosts and HTTPS CSRF origins.')
COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
# Enable only behind an ingress that removes client-supplied forwarding headers.
if getenv('TRUST_HTTPS_PROXY', 'False').lower() == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': getenv('REDIS_URL', 'redis://redis:6379/1'),
    },
}
