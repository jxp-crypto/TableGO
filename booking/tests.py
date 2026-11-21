from io import BytesIO
import json
from datetime import timedelta
from datetime import time as datetime_time
import re
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .forms import RestaurantForm
from .models import (
    FloorPlanElement, Reservation, ReservationVerification, Restaurant,
    RestaurantManager, Table,
)


class HomeRoleAccessTests(TestCase):
    def test_admin_and_manager_are_redirected_to_dashboard(self):
        admin = User.objects.create_superuser(username="admin", password="test-pass")
        manager = User.objects.create_user(username="manager", password="test-pass")
        restaurant = Restaurant.objects.create(name="Test Restaurant", slug="test-restaurant", cuisine="Test")
        RestaurantManager.objects.create(user=manager, restaurant=restaurant)

        for account in (admin, manager):
            with self.subTest(account=account.username):
                self.client.force_login(account)
                response = self.client.get(reverse("home"))
                self.assertRedirects(response, reverse("dashboard"))

    def test_admin_can_explicitly_browse_home(self):
        admin = User.objects.create_superuser(username="admin", password="test-pass")
        self.client.force_login(admin)

        response = self.client.get(reverse("home"), {"browse": "1"})

        self.assertEqual(response.status_code, 200)

    def test_customer_can_access_home(self):
        customer = User.objects.create_user(username="customer", password="test-pass")
        self.client.force_login(customer)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)


class AccountManagementTests(TestCase):
    def test_accounts_are_grouped_by_role(self):
        admin = User.objects.create_superuser(username="admin", password="test-pass")
        manager = User.objects.create_user(username="manager", password="test-pass")
        customer = User.objects.create_user(username="customer", password="test-pass")
        restaurant = Restaurant.objects.create(name="Test Restaurant", slug="test-restaurant", cuisine="Test")
        RestaurantManager.objects.create(user=manager, restaurant=restaurant)
        self.client.force_login(admin)

        response = self.client.get(reverse("d_customers"))

        self.assertEqual(response.status_code, 200)
        groups = {group["slug"]: list(group["users"]) for group in response.context["role_groups"]}
        self.assertEqual(groups["administrators"], [admin])
        self.assertEqual(groups["managers"], [manager])
        self.assertEqual(groups["customers"], [customer])
        self.assertContains(response, "Account Management")
        self.assertContains(response, "Administrators")
        self.assertContains(response, "Restaurant managers")
        self.assertContains(response, "Customers")
        self.assertNotContains(response, "Customer Management")


class ReservationCustomerNameTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_customer_name_is_saved_when_reservation_is_confirmed(self):
        customer = User.objects.create_user(username="booking_customer", password="test-pass")
        restaurant = Restaurant.objects.create(name="Test Restaurant", slug="test-restaurant", cuisine="Test")
        table = Table.objects.create(restaurant=restaurant, name="T1", seats=4)
        self.client.force_login(customer)

        url = reverse("restaurant", args=[restaurant.slug])
        details = {
            "customer_name": "Test Guest",
            "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "time": "18:00",
            "duration": "90",
            "guests": "2",
        }
        response = self.client.post(url, details)
        self.assertContains(response, "Table Selection")
        self.assertContains(response, "18:00–19:30")

        response = self.client.get(url, {**{key: value for key, value in details.items() if key != "customer_name"}, "table": table.pk})
        self.assertContains(response, "Test Guest")
        self.assertContains(response, "18:00–19:30")
        self.assertNotIn("customer_name", response.wsgi_request.GET)

        reservation_data = {
            "action": "send_code",
            "customer_name": "Test Guest",
            "date": details["date"],
            "time": details["time"],
            "duration": details["duration"],
            "guests": details["guests"],
            "table": str(table.pk),
            "email": "guest@example.com",
        }
        response = self.client.post(url, reservation_data)
        self.assertContains(response, "verification code was sent")
        self.assertEqual(Reservation.objects.count(), 0)
        code = re.search(r"\b\d{6}\b", mail.outbox[0].body).group()
        wrong_code = "000000" if code != "000000" else "000001"
        response = self.client.post(url, {
            **reservation_data,
            "action": "verify_code",
            "code": wrong_code,
        })
        self.assertContains(response, "verification code is invalid")
        self.assertEqual(Reservation.objects.count(), 0)

        response = self.client.post(url, {
            **reservation_data,
            "action": "verify_code",
            "code": code,
        })

        self.assertRedirects(response, reverse("my"))
        reservation = Reservation.objects.get(customer=customer, restaurant=restaurant)
        self.assertEqual(reservation.customer_name, "Test Guest")
        self.assertEqual(reservation.duration_minutes, 90)
        self.assertEqual(reservation.end_time, datetime_time(19, 30))
        self.assertEqual(reservation.customer_email, "guest@example.com")
        self.assertTrue(reservation.email_verified)
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_expired_email_code_cannot_create_a_reservation(self):
        customer = User.objects.create_user(username="expired_code_customer", password="test-pass")
        restaurant = Restaurant.objects.create(name="Test Restaurant", slug="expired-code", cuisine="Test")
        table = Table.objects.create(restaurant=restaurant, name="T1", seats=4)
        self.client.force_login(customer)
        url = reverse("restaurant", args=[restaurant.slug])
        details = {
            "action": "send_code",
            "customer_name": "Test Guest",
            "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "time": "18:00",
            "duration": "120",
            "guests": "2",
            "table": str(table.pk),
            "email": "guest@example.com",
        }

        self.client.post(url, details)
        challenge = ReservationVerification.objects.get(customer=customer)
        challenge.expires_at = timezone.now() - timedelta(seconds=1)
        challenge.save(update_fields=["expires_at"])
        code = re.search(r"\b\d{6}\b", mail.outbox[0].body).group()

        response = self.client.post(url, {
            **details,
            "action": "verify_code",
            "code": code,
        })

        self.assertContains(response, "code has expired")
        self.assertEqual(Reservation.objects.count(), 0)


class ReservationAvailabilityTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(
            name="Timed Restaurant",
            slug="timed-restaurant",
            cuisine="Test",
        )
        self.table = Table.objects.create(
            restaurant=self.restaurant,
            name="T1",
            seats=4,
        )
        self.day = timezone.localdate() + timedelta(days=1)

    def test_arrival_slots_respect_duration_and_operating_hours(self):
        self.assertEqual(self.restaurant.reservation_slots(120)[0], "08:00")
        self.assertEqual(self.restaurant.reservation_slots(120)[-1], "20:00")
        self.assertNotIn("20:30", self.restaurant.reservation_slots(120))

    def test_availability_excludes_only_overlapping_reservations(self):
        customer = User.objects.create_user(username="availability_customer")
        reservation = Reservation.objects.create(
            customer=customer,
            restaurant=self.restaurant,
            table=self.table,
            date=self.day,
            time="18:00",
            duration_minutes=120,
            guests=2,
        )

        self.assertEqual(reservation.end_time, datetime_time(20, 0))
        self.assertIsNone(
            self.restaurant.free_table(self.day, "19:00", 2, duration_minutes=60)
        )
        self.assertEqual(
            self.restaurant.free_table(self.day, "20:00", 2, duration_minutes=60),
            self.table,
        )


class FloorPlanEditorTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="floor_manager", password="test-pass")
        self.restaurant = Restaurant.objects.create(
            name="Floor Restaurant",
            slug="floor-restaurant",
            cuisine="Test",
        )
        RestaurantManager.objects.create(user=self.manager, restaurant=self.restaurant)
        self.table = Table.objects.create(
            restaurant=self.restaurant,
            name="T1",
            seats=4,
        )
        self.client.force_login(self.manager)

    def test_manager_can_save_table_transform(self):
        response = self.client.post(
            reverse("d_table_position", args=[self.table.pk]),
            data=json.dumps({
                "x": 40,
                "y": 35,
                "width_percent": 9,
                "height_percent": 12,
                "rotation": 45,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.table.refresh_from_db()
        self.assertEqual((self.table.x, self.table.y), (40, 35))
        self.assertEqual((self.table.width_percent, self.table.height_percent), (9, 12))
        self.assertEqual(self.table.rotation, 45)

    def test_manager_can_save_custom_floor_outline(self):
        response = self.client.post(
            reverse("d_floor_outline"),
            data=json.dumps({
                "restaurant": self.restaurant.slug,
                "points": [
                    {"x": 0, "y": 0},
                    {"x": 100, "y": 0},
                    {"x": 100, "y": 65},
                    {"x": 60, "y": 65},
                    {"x": 60, "y": 100},
                    {"x": 0, "y": 100},
                ],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(len(self.restaurant.floor_outline), 6)

    def test_manager_floor_plan_page_loads_the_editor(self):
        response = self.client.get(reverse("d_tables"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Draw boundary")
        self.assertContains(response, "booking/floor-plan.js")
        self.assertContains(response, "Landscape")
        self.assertContains(response, "Portrait")
        self.assertContains(response, "PROPERTIES")
        self.assertContains(response, "ACTIONS")
        self.assertContains(response, "ALIGN")

    def test_manager_can_create_duplicate_and_delete_table(self):
        # Create table
        create_res = self.client.post(
            reverse("d_table_create"),
            data=json.dumps({
                "restaurant": self.restaurant.slug,
                "name": "T10",
                "seats": 2,
                "min_seats": 1,
                "shape": "square",
                "section": "Dining Room",
                "x": 20,
                "y": 60,
                "rotation": 45,
            }),
            content_type="application/json",
        )
        self.assertEqual(create_res.status_code, 200)
        t10_id = create_res.json()["table"]["id"]
        table10 = Table.objects.get(pk=t10_id)
        self.assertEqual(table10.name, "T10")
        self.assertEqual(table10.rotation, 45)
        self.assertEqual(table10.section, "Dining Room")
        self.assertEqual(table10.min_seats, 1)

        # Duplicate table
        dup_res = self.client.post(
            reverse("d_table_duplicate", args=[t10_id]),
            content_type="application/json",
        )
        self.assertEqual(dup_res.status_code, 200)
        t11_id = dup_res.json()["table"]["id"]
        table11 = Table.objects.get(pk=t11_id)
        self.assertEqual(table11.name, "T11")
        self.assertEqual(table11.rotation, 45)

        # Delete table
        del_res = self.client.post(
            reverse("d_table_delete", args=[t11_id]),
            content_type="application/json",
        )
        self.assertEqual(del_res.status_code, 200)
        self.assertFalse(Table.objects.filter(pk=t11_id).exists())

    def test_manager_can_create_and_delete_floor_element(self):
        # Create Bar
        create_res = self.client.post(
            reverse("d_element_create"),
            data=json.dumps({
                "restaurant": self.restaurant.slug,
                "kind": "bar",
                "label": "Main Bar",
                "x": 75,
                "y": 50,
                "width_percent": 6,
                "height_percent": 45,
            }),
            content_type="application/json",
        )
        self.assertEqual(create_res.status_code, 200)
        elem_id = create_res.json()["element"]["id"]
        elem = FloorPlanElement.objects.get(pk=elem_id)
        self.assertEqual(elem.kind, "bar")
        self.assertEqual(elem.label, "Main Bar")

        # Create Window, Entrance, and Counter
        for kind, default_label in [("window", "Window"), ("entrance", "Entrance"), ("counter", "Counter")]:
            res = self.client.post(
                reverse("d_element_create"),
                data=json.dumps({
                    "restaurant": self.restaurant.slug,
                    "kind": kind,
                }),
                content_type="application/json",
            )
            self.assertEqual(res.status_code, 200)
            created_elem = FloorPlanElement.objects.get(pk=res.json()["element"]["id"])
            self.assertEqual(created_elem.kind, kind)
            self.assertEqual(created_elem.label, default_label)

        del_res = self.client.post(
            reverse("d_element_delete", args=[elem_id]),
            content_type="application/json",
        )
        self.assertEqual(del_res.status_code, 200)
        self.assertFalse(FloorPlanElement.objects.filter(pk=elem_id).exists())

    def test_manager_can_toggle_floor_orientation(self):
        # Initial: floor_width=10, floor_height=6 (landscape)
        self.restaurant.floor_width = 10
        self.restaurant.floor_height = 6
        self.restaurant.save()

        # Switch to portrait
        response = self.client.post(
            reverse("d_floor_orientation"),
            data=json.dumps({
                "restaurant": self.restaurant.slug,
                "orientation": "portrait",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(float(self.restaurant.floor_width), 6.0)
        self.assertEqual(float(self.restaurant.floor_height), 10.0)

        # Switch back to landscape
        response = self.client.post(
            reverse("d_floor_orientation"),
            data=json.dumps({
                "restaurant": self.restaurant.slug,
                "orientation": "landscape",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(float(self.restaurant.floor_width), 10.0)
        self.assertEqual(float(self.restaurant.floor_height), 6.0)

    def test_manager_cannot_change_another_restaurants_table(self):
        other = Restaurant.objects.create(
            name="Other Restaurant",
            slug="other-restaurant",
            cuisine="Test",
        )
        other_table = Table.objects.create(restaurant=other, name="T2", seats=2)

        response = self.client.post(
            reverse("d_table_position", args=[other_table.pk]),
            data=json.dumps({"x": 10, "y": 10}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)


class RestaurantProfileFormTests(TestCase):
    def restaurant_form_data(self):
        return {
            "name": "Image Restaurant",
            "slug": "image-restaurant",
            "cuisine": "Test",
            "location": "Naval, Biliran",
            "latitude": "11.560000",
            "longitude": "124.400000",
            "opening_time": "08:00",
            "closing_time": "22:00",
            "slot_interval_minutes": "30",
            "default_reservation_duration": "120",
            "floor_width": "10",
            "floor_height": "6",
        }

    def test_valid_image_is_accepted_and_renamed(self):
        buffer = BytesIO()
        Image.new("RGB", (4, 4), color="orange").save(buffer, format="PNG")
        upload = SimpleUploadedFile(
            "unsafe-name.jpg",
            buffer.getvalue(),
            content_type="image/jpeg",
        )
        form = RestaurantForm(self.restaurant_form_data(), {"image": upload})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["image"].name, "restaurant.png")

    def test_non_image_upload_is_rejected(self):
        upload = SimpleUploadedFile(
            "fake.jpg",
            b"MZ\x00not-an-image",
            content_type="image/jpeg",
        )
        form = RestaurantForm(self.restaurant_form_data(), {"image": upload})

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_admin_can_create_restaurant_with_image_and_map_location(self):
        admin = User.objects.create_superuser(username="profile_admin", password="test-pass")
        self.client.force_login(admin)
        buffer = BytesIO()
        Image.new("RGB", (4, 4), color="orange").save(buffer, format="PNG")
        data = {
            **self.restaurant_form_data(),
            "image": SimpleUploadedFile(
                "cover.png",
                buffer.getvalue(),
                content_type="image/png",
            ),
        }

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, GOOGLE_MAPS_API_KEY="test-google-key"):
                response = self.client.post(reverse("d_restaurants"), data)

                self.assertEqual(response.status_code, 302)
                restaurant = Restaurant.objects.get(slug="image-restaurant")
                self.assertTrue(restaurant.image.name.startswith("restaurants/"))
                self.assertTrue(restaurant.image.path.startswith(media_root))
                self.assertEqual(str(restaurant.latitude), "11.560000")

                edit_response = self.client.get(
                    reverse("d_restaurants"), {"edit": restaurant.pk}
                )
                self.assertContains(edit_response, "test-google-key")
                self.assertContains(edit_response, "Pin the restaurant location")

        public_response = self.client.get(
            reverse("restaurant", args=["image-restaurant"])
        )
        self.assertContains(public_response, "maps/dir/")
        self.assertContains(public_response, "maps?q=11.560000,124.400000")