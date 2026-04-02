from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from hanilies.admin import admin_site

urlpatterns = [
    path('admin/', admin_site.urls),
    path('', include('hanilies.urls')),
]

# Serve static files directly in production (Render free tier workaround)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)