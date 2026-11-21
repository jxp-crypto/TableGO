from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("restaurants/", views.restaurants, name="restaurants"),
    path("register/", views.register, name="register"),
    path("restaurant/<slug:slug>/", views.reserve, name="restaurant"),
    path("my/", views.my_reservations, name="my"),
    path("my/cancel/<int:pk>/", views.cancel, name="cancel"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/reservations/", views.d_reservations, name="d_reservations"),
    path("dashboard/reservations/<int:pk>/<str:status>/", views.d_status, name="d_status"),
    path("dashboard/restaurants/", views.d_restaurants, name="d_restaurants"),
    path("dashboard/tables/", views.d_tables, name="d_tables"),
    path("dashboard/tables/create/", views.d_table_create, name="d_table_create"),
    path("dashboard/tables/<int:pk>/position/", views.d_table_position, name="d_table_position"),
    path("dashboard/tables/<int:pk>/duplicate/", views.d_table_duplicate, name="d_table_duplicate"),
    path("dashboard/tables/<int:pk>/delete/", views.d_table_delete, name="d_table_delete"),
    path("dashboard/floor-elements/create/", views.d_element_create, name="d_element_create"),
    path("dashboard/floor-elements/<int:pk>/position/", views.d_element_position, name="d_element_position"),
    path("dashboard/floor-elements/<int:pk>/delete/", views.d_element_delete, name="d_element_delete"),
    path("dashboard/floor-outline/", views.d_floor_outline, name="d_floor_outline"),
    path("dashboard/floor-orientation/", views.d_floor_orientation, name="d_floor_orientation"),
    path("dashboard/floor-batch-save/", views.d_floor_batch_save, name="d_floor_batch_save"),
    path("dashboard/customers/", views.d_customers, name="d_customers"),
]
