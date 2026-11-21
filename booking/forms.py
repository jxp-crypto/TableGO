from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from .image_validation import inspect_restaurant_image
from .models import FloorPlanElement, Restaurant, Table


class TableForm(forms.ModelForm):
    class Meta:
        model = Table
        fields = [
            "name", "section", "min_seats", "seats", "shape", "x", "y", "width_percent",
            "height_percent", "rotation", "status",
        ]


class FloorPlanElementForm(forms.ModelForm):
    class Meta:
        model = FloorPlanElement
        fields = [
            "kind", "label", "x", "y", "width_percent",
            "height_percent", "rotation",
        ]


class RestaurantForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = [
            "name", "slug", "cuisine", "description", "location",
            "latitude", "longitude", "image",
            "opening_time", "closing_time", "slot_interval_minutes",
            "default_reservation_duration", "floor_width", "floor_height",
        ]

    def clean_image(self):
        upload = self.cleaned_data.get("image")
        if not isinstance(upload, UploadedFile):
            return upload
        try:
            extension = inspect_restaurant_image(upload)
        except ValidationError as exc:
            raise ValidationError(exc.messages) from exc
        upload.name = f"restaurant{extension}"
        return upload

    def clean(self):
        cleaned_data = super().clean()
        opening = cleaned_data.get("opening_time")
        closing = cleaned_data.get("closing_time")
        if opening and closing and closing <= opening:
            self.add_error("closing_time", "Closing time must be later than opening time.")
        if (cleaned_data.get("latitude") is None) != (cleaned_data.get("longitude") is None):
            self.add_error("longitude", "Enter both latitude and longitude, or leave both blank.")
        floor_width = cleaned_data.get("floor_width")
        floor_height = cleaned_data.get("floor_height")
        if floor_width is not None and floor_width <= 0:
            self.add_error("floor_width", "Floor width must be greater than zero.")
        if floor_height is not None and floor_height <= 0:
            self.add_error("floor_height", "Floor height must be greater than zero.")
        return cleaned_data

    def save(self, commit=True):
        restaurant = super().save(commit=False)
        restaurant.hours = (
            f"{restaurant.opening_time.strftime('%I:%M %p')} - "
            f"{restaurant.closing_time.strftime('%I:%M %p')}"
        )
        if commit:
            restaurant.save()
            self.save_m2m()
        return restaurant
