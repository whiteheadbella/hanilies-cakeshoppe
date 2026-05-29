from django.urls import include, path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from hanilies.admin import admin_site


def media_serve(request, path):
    return serve(request, path, document_root=settings.MEDIA_ROOT)

urlpatterns = [
    path('admin/', admin_site.urls),
    path('', include('hanilies.urls')),
    re_path(r'^media/(?P<path>.*)$', media_serve),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)