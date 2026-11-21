from django.contrib import admin
from .models import (
    FloorPlanElement, Reservation, Restaurant, RestaurantManager, Table,
)


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "cuisine", "active")
    list_editable = ("active",)
    list_filter = ("active",)
    actions = ("activate_restaurants", "deactivate_restaurants")
    prepopulated_fields = {"slug": ("name",)}

    @admin.action(description="Activate selected restaurants")
    def activate_restaurants(self, request, queryset):
        queryset.update(active=True)

    @admin.action(description="Deactivate selected restaurants")
    def deactivate_restaurants(self, request, queryset):
        queryset.update(active=False)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "restaurant", "customer_name", "customer_email", "email_verified",
        "date", "time", "end_time", "guests", "table", "status",
    )
    list_filter = ("restaurant", "status", "date")
    actions = ["confirm", "decline"]

    @admin.action(description="Confirm selected reservations")
    def confirm(self, request, qs):
        qs.update(status="confirmed")

    @admin.action(description="Decline selected reservations")
    def decline(self, request, qs):
        qs.update(status="declined")


admin.site.register([Table, RestaurantManager, FloorPlanElement])
