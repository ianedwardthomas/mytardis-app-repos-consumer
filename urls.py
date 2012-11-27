from django.conf.urls.defaults import patterns, url

urlpatterns = patterns('',
    url(r'^$', 'tardis.apps.reposconsumer.views.hello', name="hello"),
)