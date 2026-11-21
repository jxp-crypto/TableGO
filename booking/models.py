
from uuid import uuid4
from datetime import datetime, time as datetime_time, timedelta

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .image_validation import (
    inspect_restaurant_image,
    validate_restaurant_image,
)


LIVE = ["pending", "confirmed"]

FLOOR_ELEMENT_KINDS = [
    ("wall", "Wall"),
    ("entrance", "Entrance"),
    ("exit", "Exit"),
    ("reception", "Reception"),
    ("kitchen", "Kitchen"),
    ("restroom", "Restroom"),
    ("window", "Window"),
    ("partition", "Partition"),
    ("zone", "Dining zone"),
    ("bar", "Bar counter"),
    ("counter", "Counter"),
]

TABLE_STATUSES = [
    ("available", "Available"),
    ("occupied", "Occupied"),
    ("unavailable", "Unavailable"),
]


# ==========================================================
# TIME FORMAT HELPER
# Converts 24-hour time to 12-hour AM/PM for display only.
# ==========================================================

def format_time_12h(value):
    if not value:
        return ""

    if isinstance(value, str):
        value = datetime.strptime(value, "%H:%M").time()

    return value.strftime("%I:%M %p").lstrip("0")


# ==========================================================
# RESTAURANT
# ==========================================================

def restaurant_image_upload_path(instance, filename):
    extension = inspect_restaurant_image(instance.image)
    return f"restaurants/{uuid4().hex}{extension}"


class Restaurant(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    cuisine = models.CharField(max_length=80)
    description = models.TextField(blank=True)

    fixtures = models.JSONField(
        default=list,
        blank=True,
        help_text="Floor-plan areas: label, x, y, w, h"
    )

    floor_width = models.DecimalField(
        max_digits=6, decimal_places=2, default=10
    )
    floor_height = models.DecimalField(
        max_digits=6, decimal_places=2, default=6
    )
    floor_outline = models.JSONField(default=list, blank=True)

    location = models.CharField(max_length=80, blank=True)

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )

    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    image = models.ImageField(
        upload_to=restaurant_image_upload_path,
        null=True,
        blank=True,
        validators=[validate_restaurant_image],
    )

    hours = models.CharField(max_length=60, blank=True)

    opening_time = models.TimeField(
        default=datetime_time(8, 0)
    )

    closing_time = models.TimeField(
        default=datetime_time(22, 0)
    )

    slot_interval_minutes = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(15), MaxValueValidator(180)]
    )

    default_reservation_duration = models.PositiveSmallIntegerField(
        default=120,
        validators=[MinValueValidator(30), MaxValueValidator(480)]
    )

    active = models.BooleanField(default=True)

    @property
    def display_opening_time(self):
        return format_time_12h(self.opening_time)

    @property
    def display_closing_time(self):
        return format_time_12h(self.closing_time)

    @property
    def fallback_image_path(self):
        if self.slug in {"khloe", "golden-sun", "lub-dub-cafe"}:
            return f"booking/img/{self.slug}.jpg"

        return "booking/img/restaurant-default.svg"

    def reservation_slots(self, duration_minutes=None):
        """Return reservation arrival times in 24-hour format."""

        duration = (
            duration_minutes or self.default_reservation_duration
        )

        opening = datetime.combine(
            datetime.min.date(),
            self.opening_time
        )

        closing = datetime.combine(
            datetime.min.date(),
            self.closing_time
        )

        last_start = closing - timedelta(minutes=duration)

        slots = []
        current = opening

        while current <= last_start:
            # Keep 24-hour format for backend processing.
            slots.append(current.strftime("%H:%M"))

            current += timedelta(
                minutes=self.slot_interval_minutes
            )

        return slots

    def free_table(self, date, time, guests, duration_minutes=None):
        """Find the smallest available table that fits the guests."""

        start = datetime.strptime(time, "%H:%M")

        end = start + timedelta(
            minutes=(
                duration_minutes
                or self.default_reservation_duration
            )
        )

        busy = self.reservation_set.filter(
            date=date,
            status__in=LIVE,
            time__lt=end.strftime("%H:%M"),
            end_time__gt=start.time(),
        ).values_list("table_id", flat=True)

        return (
            self.table_set.filter(
                seats__gte=guests,
                status="available"
            )
            .exclude(id__in=busy)
            .order_by("seats")
            .first()
        )

    def __str__(self):
        return self.name


# ==========================================================
# RESTAURANT MANAGER
# ==========================================================

class RestaurantManager(models.Model):
    """Links a user account to the one restaurant they manage."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="manager"
    )

    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.user} manages {self.restaurant}"


# ==========================================================
# TABLE
# ==========================================================

class Table(models.Model):
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE
    )

    name = models.CharField(max_length=20)

    seats = models.PositiveSmallIntegerField(
        help_text="Maximum seats"
    )

    min_seats = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text="Minimum seats"
    )

    section = models.CharField(
        max_length=40,
        default="Dining Room",
        blank=True
    )

    shape = models.CharField(
        max_length=10,
        default="square",
        choices=[
            ("square", "Square"),
            ("rect", "Rectangle"),
            ("long", "Long"),
            ("banquet", "Banquet"),
            ("round", "Round"),
        ]
    )

    x = models.PositiveSmallIntegerField(
        default=50,
        help_text="Horizontal position on the floor plan, 0-100"
    )

    y = models.PositiveSmallIntegerField(
        default=50,
        help_text="Vertical position on the floor plan, 0-100"
    )

    width_percent = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(3), MaxValueValidator(40)]
    )

    height_percent = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(3), MaxValueValidator(40)]
    )

    rotation = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(359)]
    )

    status = models.CharField(
        max_length=12,
        choices=TABLE_STATUSES,
        default="available"
    )

    def __str__(self):
        return f"{self.restaurant.name} {self.name} ({self.seats})"


# ==========================================================
# FLOOR PLAN ELEMENT
# ==========================================================

class FloorPlanElement(models.Model):
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="floor_elements"
    )

    kind = models.CharField(
        max_length=12,
        choices=FLOOR_ELEMENT_KINDS
    )

    label = models.CharField(max_length=60)

    x = models.PositiveSmallIntegerField(default=50)

    y = models.PositiveSmallIntegerField(default=50)

    width_percent = models.PositiveSmallIntegerField(
        default=14,
        validators=[MinValueValidator(3), MaxValueValidator(100)]
    )

    height_percent = models.PositiveSmallIntegerField(
        default=12,
        validators=[MinValueValidator(3), MaxValueValidator(100)]
    )

    rotation = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(359)]
    )

    def __str__(self):
        return f"{self.label} ({self.restaurant.name})"


# ==========================================================
# RESERVATION
# ==========================================================

class Reservation(models.Model):

    STATUS = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("declined", "Declined"),
        ("cancelled", "Cancelled"),
    ]

    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    customer_name = models.CharField(
        max_length=100,
        blank=True
    )

    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE
    )

    table = models.ForeignKey(
        Table,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    date = models.DateField()

    # Keep the original 24-hour database format.
    time = models.CharField(max_length=5)

    duration_minutes = models.PositiveSmallIntegerField(
        default=120,
        validators=[MinValueValidator(30), MaxValueValidator(480)]
    )

    end_time = models.TimeField(
        null=True,
        blank=True
    )

    customer_email = models.EmailField(blank=True)

    email_verified = models.BooleanField(default=False)

    guests = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(20)]
    )

    phone = models.CharField(max_length=30, blank=True)

    occasion = models.CharField(max_length=30, blank=True)

    note = models.CharField(max_length=200, blank=True)

    status = models.CharField(
        max_length=10,
        choices=STATUS,
        default="pending"
    )

    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "time"]

    # Display reservation time in 12-hour format.
    @property
    def display_time(self):
        return format_time_12h(self.time)

    # Display reservation ending time in 12-hour format.
    @property
    def display_end_time(self):
        return format_time_12h(self.end_time)

    def save(self, *args, **kwargs):
        # Keep reservation calculations in 24-hour format.
        start = datetime.strptime(self.time, "%H:%M")

        end = start + timedelta(
            minutes=self.duration_minutes
        )

        if end.date() != start.date():
            raise ValueError(
                "A reservation cannot continue past midnight."
            )

        self.end_time = end.time()

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"R{self.pk} {self.restaurant} "
            f"{self.date} {self.time}"
        )


# ==========================================================
# RESERVATION EMAIL VERIFICATION
# ==========================================================

class ReservationVerification(models.Model):

    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    email = models.EmailField()

    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE
    )

    table = models.ForeignKey(
        Table,
        on_delete=models.CASCADE
    )

    date = models.DateField()

    # Keep the original 24-hour format.
    time = models.CharField(max_length=5)

    duration_minutes = models.PositiveSmallIntegerField()

    guests = models.PositiveSmallIntegerField()

    customer_name = models.CharField(max_length=100)

    phone = models.CharField(max_length=30, blank=True)

    occasion = models.CharField(max_length=30, blank=True)

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )

    code_hash = models.CharField(max_length=128)

    expires_at = models.DateTimeField()

    last_sent_at = models.DateTimeField()

    attempts = models.PositiveSmallIntegerField(default=0)

    resend_count = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    verified_at = models.DateTimeField(
        null=True,
        blank=True
    )

    used_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # Display verification reservation time in AM/PM.
    @property
    def display_time(self):
        return format_time_12h(self.time)

    class Meta:
        indexes = [
            models.Index(
                fields=["customer", "email", "created_at"]
            ),
            models.Index(
                fields=["ip_address", "created_at"]
            ),
        ]
