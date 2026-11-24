from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("aziende/nuova/", views.company_create, name="company_create"),
    path("aziende/<int:pk>/", views.company_detail, name="company"),
    path("aziende/<int:pk>/nuova-valutazione/", views.assessment_create, name="assessment_create"),
    path("valutazioni/<int:pk>/", views.assessment_detail, name="assessment"),
    path("valutazioni/<int:pk>/revisioni/<int:rid>/", views.revision_detail, name="revision"),
    path("valutazioni/<int:pk>/revisioni/<int:rid>/correggi/", views.revision_create, name="revision_create"),
    path("valutazioni/<int:pk>/revisioni/<int:rid>/pubblica/", views.revision_publish, name="revision_publish"),
    path("valutazioni/<int:pk>/revisioni/<int:rid>/annulla/", views.revision_discard, name="revision_discard"),
    path("valutazioni/<int:pk>/revisioni/<int:rid>/voci/<int:row_id>/", views.probability_save, name="probability_save"),
    path("valutazioni/<int:pk>/revisioni/<int:rid>/voci/<int:row_id>/comando/", views.probability_bulk, name="probability_bulk"),
    path("catalogo/", views.catalog_detail, name="catalog"),
    path("catalogo/bozza/", views.catalog_start, name="catalog_start"),
    path("catalogo/<int:vid>/pubblica/", views.catalog_publish, name="catalog_publish"),
    path("catalogo/<int:vid>/annulla/", views.catalog_discard, name="catalog_discard"),
    path("catalogo/<int:vid>/categorie/nuova/", views.catalog_category, name="catalog_category_create"),
    path("catalogo/<int:vid>/categorie/<int:cid>/", views.catalog_category, name="catalog_category"),
    path("catalogo/<int:vid>/sottocategorie/nuova/", views.catalog_row, name="catalog_row_create"),
    path("catalogo/<int:vid>/sottocategorie/<int:row_id>/", views.catalog_row, name="catalog_row"),
    path("catalogo/<int:vid>/pericoli/nuovo/", views.catalog_hazard, name="catalog_hazard_create"),
    path("catalogo/<int:vid>/pericoli/<int:hid>/", views.catalog_hazard, name="catalog_hazard"),
]
