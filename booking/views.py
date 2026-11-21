import logging
import json
import secrets
import smtplib
from datetime import date as dt, datetime, timedelta
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import FloorPlanElementForm, RestaurantForm, TableForm
from .models import (
    FloorPlanElement, LIVE, Reservation, ReservationVerification,
    Restaurant, Table,
)

OCCASIONS = ["", "Birthday", "Anniversary", "Business meeting", "Date night", "Family gathering"]
DURATION_CHOICES = [60, 90, 120, 180]
logger = logging.getLogger(__name__)


def _duration_from_request(src, default):
    requested = src.get("duration", "")
    try:
        duration = int(src.get("custom_duration", "")) if requested == "custom" else int(requested or default)
    except (TypeError, ValueError):
        return default, False
    valid = (
        30 <= duration <= 480
        and duration % 30 == 0
        and (
            requested == "custom"
            or duration in DURATION_CHOICES
            or duration == default
        )
    )
    return (duration if valid else default), valid


def _busy_table_ids(restaurant, day, start_time, duration):
    start = datetime.strptime(start_time, "%H:%M")
    end = start + timedelta(minutes=duration)
    return set(
        Reservation.objects.filter(
            restaurant=restaurant,
            date=day,
            status__in=LIVE,
            time__lt=end.strftime("%H:%M"),
            end_time__gt=start.time(),
        ).values_list("table_id", flat=True)
    )


def _send_email(subject, body, recipient):
    try:
        sent = send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
    except (OSError, smtplib.SMTPException):
        logger.exception("TableGO could not send an email.")
        return False
    if sent != 1:
        logger.error("TableGO email backend did not confirm delivery.")
        return False
    return True


def _send_verification_code(challenge, code):
    body = (
        f"Your TableGO reservation verification code is {code}.\n\n"
        "It expires in 10 minutes. Do not share this code with anyone."
    )
    return _send_email("Verify your TableGO reservation email", body, challenge.email)


def _verification_rate_limited(user, email, ip_address, now):
    recent = ReservationVerification.objects.filter(
        created_at__gte=now - timedelta(hours=1)
    )
    if recent.filter(customer=user, email__iexact=email).count() >= 5:
        return True
    return bool(ip_address and recent.filter(ip_address=ip_address).count() >= 10)


def _start_email_verification(request, restaurant, table, day, start_time,
                              duration, guests, customer_name, phone, occasion,
                              email, session_key):
    now = timezone.now()
    ip_address = request.META.get("REMOTE_ADDR")
    if _verification_rate_limited(request.user, email, ip_address, now):
        messages.error(request, "Too many verification requests. Please try again later.")
        return None

    previous_id = request.session.get(session_key)
    if previous_id:
        ReservationVerification.objects.filter(
            pk=previous_id, customer=request.user, used_at__isnull=True
        ).update(expires_at=now)

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = ReservationVerification.objects.create(
        customer=request.user,
        email=email,
        restaurant=restaurant,
        table=table,
        date=day,
        time=start_time,
        duration_minutes=duration,
        guests=guests,
        customer_name=customer_name,
        phone=phone,
        occasion=occasion,
        ip_address=ip_address,
        code_hash=make_password(code),
        expires_at=now + timedelta(minutes=10),
        last_sent_at=now,
    )
    if not _send_verification_code(challenge, code):
        challenge.delete()
        messages.error(request, "We could not send the verification email. Check the email configuration and try again.")
        return None
    request.session[session_key] = challenge.pk
    messages.success(request, f"A verification code was sent to {email}.")
    return challenge


def _resend_email_verification(request, challenge):
    now = timezone.now()
    if challenge.last_sent_at + timedelta(seconds=60) > now:
        messages.error(request, "Wait 60 seconds before requesting another code.")
        return False
    if challenge.resend_count >= 3:
        messages.error(request, "This verification has reached its resend limit. Start a new reservation verification.")
        return False
    if _verification_rate_limited(
        request.user, challenge.email, challenge.ip_address, now
    ):
        messages.error(request, "Too many verification requests. Please try again later.")
        return False

    old_state = (
        challenge.code_hash,
        challenge.expires_at,
        challenge.last_sent_at,
        challenge.attempts,
        challenge.resend_count,
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge.code_hash = make_password(code)
    challenge.expires_at = now + timedelta(minutes=10)
    challenge.last_sent_at = now
    challenge.attempts = 0
    challenge.resend_count += 1
    challenge.save(update_fields=[
        "code_hash", "expires_at", "last_sent_at", "attempts", "resend_count",
    ])
    if not _send_verification_code(challenge, code):
        (
            challenge.code_hash,
            challenge.expires_at,
            challenge.last_sent_at,
            challenge.attempts,
            challenge.resend_count,
        ) = old_state
        challenge.save(update_fields=[
            "code_hash", "expires_at", "last_sent_at", "attempts", "resend_count",
        ])
        messages.error(request, "We could not send a new verification email. Please try again later.")
        return False
    messages.success(request, f"A new verification code was sent to {challenge.email}.")
    return True


def _verify_email_code(request, challenge, code):
    with transaction.atomic():
        challenge = ReservationVerification.objects.select_for_update().get(
            pk=challenge.pk, customer=request.user
        )
        now = timezone.now()
        if challenge.used_at is not None:
            messages.error(request, "This verification code has already been used.")
            return None
        if challenge.expires_at <= now:
            messages.error(request, "That code has expired. Request a new code.")
            return None
        if challenge.attempts >= 5:
            messages.error(request, "Too many incorrect codes. Request a new code.")
            return None
        if len(code) != 6 or not code.isdigit() or not check_password(code, challenge.code_hash):
            challenge.attempts += 1
            if challenge.attempts >= 5:
                challenge.expires_at = now
            challenge.save(update_fields=["attempts", "expires_at"])
            messages.error(request, "That verification code is invalid.")
            return None

        restaurant = Restaurant.objects.select_for_update().get(pk=challenge.restaurant_id)
        table = Table.objects.select_for_update().filter(
            pk=challenge.table_id,
            restaurant=restaurant,
            status="available",
            seats__gte=challenge.guests,
        ).first()
        slots = restaurant.reservation_slots(challenge.duration_minutes)
        busy = _busy_table_ids(
            restaurant, challenge.date, challenge.time, challenge.duration_minutes
        )
        if (
            table is None
            or table.pk in busy
            or challenge.date < timezone.localdate()
            or challenge.time not in slots
        ):
            challenge.expires_at = now
            challenge.save(update_fields=["expires_at"])
            messages.error(request, "That table or time is no longer available. Start the reservation again.")
            return None

        reservation = Reservation.objects.create(
            customer=challenge.customer,
            customer_name=challenge.customer_name,
            customer_email=challenge.email,
            email_verified=True,
            restaurant=restaurant,
            table=table,
            date=challenge.date,
            time=challenge.time,
            duration_minutes=challenge.duration_minutes,
            guests=challenge.guests,
            phone=challenge.phone,
            occasion=challenge.occasion,
        )
        challenge.verified_at = now
        challenge.used_at = now
        challenge.save(update_fields=["verified_at", "used_at"])
    return reservation


def _challenge_matches(challenge, restaurant, day, start_time, duration,
                       guests, customer_name, phone, occasion, table_id):
    return (
        challenge.restaurant_id == restaurant.pk
        and challenge.date == day
        and challenge.time == start_time
        and challenge.duration_minutes == duration
        and challenge.guests == guests
        and challenge.customer_name == customer_name
        and challenge.phone == phone
        and challenge.occasion == occasion
        and str(challenge.table_id) == str(table_id)
    )


def _send_reservation_confirmation(reservation):
    body = (
        f"Hi {reservation.customer_name},\n\n"
        f"Your reservation request at {reservation.restaurant.name} has been received.\n"
        f"Date: {reservation.date.strftime('%B %d, %Y')}\n"
        f"Time: {reservation.time}-{reservation.end_time:%H:%M}\n"
        f"Duration: {reservation.duration_minutes} minutes\n"
        f"Guests: {reservation.guests}\n"
        f"Table: {reservation.table.name}\n\n"
        "The restaurant will review and confirm your request."
    )
    return _send_email(
        "TableGO reservation request received", body, reservation.customer_email
    )


# ---------- Customer ----------
def home(request):
    is_manager = request.user.is_authenticated and getattr(request.user, "manager", None)
    is_admin_browsing_dashboard = request.user.is_authenticated and request.user.is_staff and request.GET.get("browse") != "1"
    if is_manager or is_admin_browsing_dashboard:
        return redirect("dashboard")
    return render(request, "home.html", {"restaurants": Restaurant.objects.filter(active=True)})


def restaurants(request):
    return render(request, "restaurants.html", {"restaurants": Restaurant.objects.filter(active=True)})


def register(request):
    form = UserCreationForm(request.POST or None)
    form.fields["username"].help_text = ""
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        return redirect("home")
    return render(request, "registration/register.html", {"form": form})


def reserve(request, slug):
    """Reservation details, table selection, and email verification."""
    rest = get_object_or_404(Restaurant, slug=slug, active=True)
    src = request.POST if request.method == "POST" else request.GET
    today = timezone.localdate()
    try:
        d = dt.fromisoformat(src.get("date", ""))
    except ValueError:
        d = None
    duration, valid_duration = _duration_from_request(
        src, rest.default_reservation_duration
    )
    requested_duration = src.get("duration", "")
    duration_selector = (
        "custom"
        if requested_duration == "custom"
        or (requested_duration and not requested_duration.isdigit())
        else str(duration)
    )
    slots = rest.reservation_slots(duration)
    requested_time = src.get("time", "")
    valid_time = not requested_time or requested_time in slots
    t = requested_time if requested_time in slots else (slots[0] if slots else "")
    try:
        g = max(1, min(20, int(src.get("guests", 1))))
    except ValueError:
        g = 2
    occ, phone = src.get("occasion", "")[:30], src.get("phone", "")[:30]
    session_key = f"reservation_name_{slug}"
    verification_key = f"reservation_verification_{slug}"
    default_name = request.user.get_full_name() if request.user.is_authenticated else ""
    name_value = src.get("customer_name", request.session.get(session_key, default_name))
    customer_name = (name_value or "").strip()[:100]
    email = (src.get("email", "") or "").strip().lower()
    action = src.get("action", "")
    step, cells, pick = 1, [], None
    if not valid_duration and request.method == "POST":
        messages.error(request, "Choose a valid reservation duration (30-minute increments, up to 8 hours).")
    if not slots:
        messages.error(request, "This reservation duration does not fit within the restaurant's opening hours.")
    if not valid_time and request.method == "POST":
        messages.error(request, "Choose an available arrival time.")
    if d and d >= today and slots and valid_duration and valid_time:
        step = 2
        busy = _busy_table_ids(rest, d, t, duration)
        cells = [
            {
                "t": table,
                "state": (
                    "unavailable"
                    if table.status == "unavailable"
                    else "occupied"
                    if table.status == "occupied"
                    else "taken"
                    if table.pk in busy
                    else "small"
                    if table.seats < g
                    else "free"
                ),
            }
            for table in rest.table_set.all()
        ]
        pick = next((c["t"] for c in cells if str(c["t"].pk) == src.get("table") and c["state"] == "free"), None)
        if pick:
            step = 3
    elif d and d < today:
        messages.error(request, "Pick today or a later date.")
    if request.method == "POST" and d is None:
        messages.error(request, "Choose a valid reservation date.")
    verification_actions = {"send_code", "resend_code", "verify_code"}
    if request.method == "POST" and action not in verification_actions:
        if customer_name:
            request.session[session_key] = customer_name
        else:
            messages.error(request, "Enter your name to continue.")
            step, cells, pick = 1, [], None

    verification = None
    if request.method == "POST" and action == "send_code":
        if not request.user.is_authenticated:
            messages.error(request, "Log in or sign up before verifying your reservation email.")
        elif step != 3 or pick is None:
            messages.error(request, "Choose an available table before verifying your email.")
        else:
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, "Enter a valid email address.")
            else:
                verification = _start_email_verification(
                    request, rest, pick, d, t, duration, g, customer_name,
                    phone, occ, email, verification_key,
                )
    elif request.method == "POST" and action in {"resend_code", "verify_code"}:
        challenge = None
        if request.user.is_authenticated:
            challenge = ReservationVerification.objects.filter(
                pk=request.session.get(verification_key),
                customer=request.user,
                used_at__isnull=True,
            ).first()
        if challenge is None:
            messages.error(request, "Your verification session has expired. Request a new code.")
            request.session.pop(verification_key, None)
        elif not _challenge_matches(
            challenge, rest, d, t, duration, g, customer_name, phone, occ,
            src.get("table", ""),
        ):
            challenge.expires_at = timezone.now()
            challenge.save(update_fields=["expires_at"])
            request.session.pop(verification_key, None)
            messages.error(request, "Reservation details changed. Request a new verification code.")
        elif action == "resend_code":
            _resend_email_verification(request, challenge)
            verification = challenge
        else:
            reservation = _verify_email_code(request, challenge, (src.get("code") or "").strip())
            if reservation is None:
                verification = challenge
            else:
                request.session.pop(verification_key, None)
                request.session.pop(session_key, None)
                messages.success(
                    request,
                    f"Reservation RSV-{reservation.pk + 1000} requested at {rest.name} "
                    f"(table {reservation.table.name}, {reservation.time}-"
                    f"{reservation.end_time:%H:%M}). Awaiting confirmation.",
                )
                if _send_reservation_confirmation(reservation):
                    messages.success(request, "A reservation confirmation was emailed to you.")
                else:
                    messages.warning(
                        request,
                        "Your reservation was saved, but we could not send the confirmation email.",
                    )
                return redirect("my")

    if verification is None and request.user.is_authenticated:
        verification = ReservationVerification.objects.filter(
            pk=request.session.get(verification_key),
            customer=request.user,
            used_at__isnull=True,
        ).first()
    if verification and not _challenge_matches(
        verification, rest, d, t, duration, g, customer_name, phone, occ,
        src.get("table", ""),
    ):
        verification.expires_at = timezone.now()
        verification.save(update_fields=["expires_at"])
        request.session.pop(verification_key, None)
        verification = None

    sel = {"date": d if d and d >= today else today, "time": t, "guests": g, "occasion": occ,
           "phone": phone, "customer_name": customer_name, "duration": duration,
           "email": verification.email if verification else email}
    duration_choices = []
    for minutes in sorted(set(DURATION_CHOICES + [rest.default_reservation_duration])):
        hours = minutes / 60
        label = f"{hours:g} hour" if hours == 1 else f"{hours:g} hours"
        duration_choices.append({"value": minutes, "label": label})
    end_time = None
    if t:
        end_time = (
            datetime.strptime(t, "%H:%M") + timedelta(minutes=duration)
        ).time()
    return render(request, "reserve.html", {"rest": rest, "step": step, "cells": cells, "pick": pick, "sel": sel,
                                            "slots": slots, "occasions": OCCASIONS, "today": today,
                                            "duration_choices": duration_choices, "end_time": end_time,
                                            "duration_selector": duration_selector,
                                            "verification": verification})


@login_required
def my_reservations(request):
    today, tab = timezone.localdate(), request.GET.get("tab", "upcoming")
    qs = list(Reservation.objects.filter(customer=request.user).select_related("restaurant", "table"))
    groups = {"upcoming": [r for r in qs if r.status in LIVE and r.date >= today],
              "completed": [r for r in qs if r.status in LIVE and r.date < today],
              "cancelled": [r for r in qs if r.status in ("cancelled", "declined")]}
    return render(request, "my.html", {"tab": tab, "items": groups.get(tab, []), "counts": {k: len(v) for k, v in groups.items()}})


@login_required
@require_POST
def cancel(request, pk):
    r = get_object_or_404(Reservation, pk=pk, customer=request.user)
    if r.status in LIVE:
        r.status = "cancelled"
        r.save()
    return redirect("my")


# ---------- Dashboard (admin = all restaurants, manager = own restaurant) ----------
def dash_only(fn):
    @wraps(fn)
    @login_required
    def wrapper(request, *a, **k):
        if request.user.is_staff:
            rests, is_admin = Restaurant.objects.all(), True
        elif getattr(request.user, "manager", None):
            rests, is_admin = Restaurant.objects.filter(pk=request.user.manager.restaurant_id), False
        else:
            raise PermissionDenied
        return fn(request, rests, is_admin, *a, **k)
    return wrapper


def dash(request, tpl, is_admin, nav, **ctx):
    return render(request, tpl, {"is_admin": is_admin, "nav": nav, **ctx})


@dash_only
def dashboard(request, rests, is_admin):
    res = Reservation.objects.filter(restaurant__in=rests)
    cur = rests.filter(slug=request.GET.get("r")).first() or rests.first()
    cells = []
    if cur:
        booked = set(res.filter(restaurant=cur, date=timezone.localdate(), status__in=LIVE).values_list("table_id", flat=True))
        cells = [
            {
                "t": table,
                "state": (
                    "unavailable"
                    if table.status == "unavailable"
                    else "occupied"
                    if table.status == "occupied"
                    else "taken"
                    if table.pk in booked
                    else "free"
                ),
            }
            for table in cur.table_set.all()
        ]
    custs = User.objects.filter(is_staff=False).count() if is_admin else res.values("customer").distinct().count()
    stats = [("Total Reservations", res.count()), ("Tables", Table.objects.filter(restaurant__in=rests).count()),
             ("Pending Approval", res.filter(status="pending").count()), ("Total Customers", custs)]
    latest = res.select_related("customer", "restaurant", "table").order_by("-created")
    return dash(request, "dash.html", is_admin, "dashboard", rests=rests.annotate(nt=Count("table")), cur=cur, cells=cells,
                stats=stats, recent=latest[:5], activity=latest[:5])


@dash_only
def d_reservations(request, rests, is_admin):
    status, slug = request.GET.get("status", ""), request.GET.get("r", "")
    items = Reservation.objects.filter(restaurant__in=rests).select_related("customer", "restaurant", "table").order_by("-date", "-time")
    if status:
        items = items.filter(status=status)
    if slug:
        items = items.filter(restaurant__slug=slug)
    return dash(request, "d_reservations.html", is_admin, "reservations", rests=rests, items=items, status=status, slug=slug)


@dash_only
@require_POST
def d_status(request, rests, is_admin, pk, status):
    if status in ("confirmed", "declined"):
        Reservation.objects.filter(pk=pk, restaurant__in=rests).update(status=status)
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/dashboard") else "dashboard")


@dash_only
def d_restaurants(request, rests, is_admin):
    if not is_admin:
        raise PermissionDenied
    edit_pk = request.POST.get("edit") if request.method == "POST" else request.GET.get("edit")
    edit_restaurant = rests.filter(pk=edit_pk).first() if edit_pk else None
    if edit_pk and edit_restaurant is None:
        raise PermissionDenied
    form = RestaurantForm(instance=edit_restaurant)
    if request.method == "POST":
        if request.POST.get("action") == "toggle":
            r = get_object_or_404(Restaurant, pk=request.POST.get("pk"))
            r.active = not r.active
            r.save()
            return redirect("d_restaurants")
        form = RestaurantForm(request.POST, request.FILES, instance=edit_restaurant)
        if form.is_valid():
            form.save()
            return redirect("d_restaurants")
    today = timezone.localdate()
    rows = rests.annotate(nt=Count("table", distinct=True))
    for r in rows:
        r.today = r.reservation_set.filter(date=today, status__in=LIVE).count()
        r.pend = r.reservation_set.filter(status="pending").count()
    return dash(
        request, "d_restaurants.html", is_admin, "restaurants",
        rows=rows, form=form, maps_api_key=settings.GOOGLE_MAPS_API_KEY,
    )


@dash_only
def d_tables(request, rests, is_admin):
    cur = rests.filter(slug=request.GET.get("r") or request.POST.get("r")).first() or rests.first()
    form = TableForm()
    element_form = FloorPlanElementForm()
    if request.method == "POST" and cur:
        a, pk = request.POST.get("action"), request.POST.get("pk")
        back = redirect(f"{reverse('d_tables')}?r={cur.slug}")
        if a == "add_table":
            form = TableForm(request.POST)
            if form.is_valid():
                form.instance.restaurant = cur
                form.save()
                return back
        elif a == "del_table":
            Table.objects.filter(pk=pk, restaurant=cur).delete()
            return back
        elif a == "edit_table":
            try:
                table = get_object_or_404(Table, pk=pk, restaurant=cur)
                table.name = request.POST.get("name", table.name).strip()[:20]
                table.section = request.POST.get("section", table.section).strip()[:40]
                table.x = int(request.POST["x"])
                table.y = int(request.POST["y"])
                table.seats = int(request.POST["seats"])
                table.min_seats = _optional_int(request.POST.get("min_seats")) or 1
                table.width_percent = _optional_int(request.POST.get("width_percent"))
                table.height_percent = _optional_int(request.POST.get("height_percent"))
                table.rotation = int(request.POST.get("rotation", table.rotation))
                table.status = request.POST["status"]
                if not 0 <= table.x <= 100 or not 0 <= table.y <= 100:
                    raise ValueError
                if not 1 <= table.seats <= 30 or not 1 <= table.min_seats <= 30:
                    raise ValueError
                if table.width_percent is not None and not 3 <= table.width_percent <= 40:
                    raise ValueError
                if table.height_percent is not None and not 3 <= table.height_percent <= 40:
                    raise ValueError
                if not 0 <= table.rotation <= 359:
                    raise ValueError
                if table.status not in {"available", "occupied", "unavailable"}:
                    raise ValueError
                table.save()
            except (ValueError, KeyError):
                messages.error(request, "Enter valid table positions, dimensions, seats, and rotation.")
            return back
        elif a == "add_element":
            element_form = FloorPlanElementForm(request.POST)
            if element_form.is_valid():
                element_form.instance.restaurant = cur
                element_form.save()
                return back
        elif a == "del_element":
            FloorPlanElement.objects.filter(pk=pk, restaurant=cur).delete()
            return back
    tables = cur.table_set.all() if cur else []
    default_sections = ["Dining Room", "Patio", "Bar", "Main Hall", "Balcony", "Terrace", "Private Room"]
    existing_sections = list(cur.table_set.values_list("section", flat=True).distinct()) if cur else []
    sections = list(dict.fromkeys(default_sections + [s for s in existing_sections if s]))
    orientation = "landscape" if cur and cur.floor_width >= cur.floor_height else "portrait"
    return dash(request, "d_tables.html", is_admin, "tables", rests=rests, cur=cur, form=form, tables=tables,
                cells=[
                    {"t": table, "state": "free" if table.status == "available" else table.status}
                    for table in tables
                ],
                element_form=element_form,
                elements=cur.floor_elements.all() if cur else [],
                outline=cur.floor_outline if cur else [],
                sections=sections,
                orientation=orientation)


def _optional_int(value):
    return int(value) if value not in (None, "") else None


def _json_body(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"error": "Invalid JSON request."}, status=400)
    if not isinstance(body, dict):
        return None, JsonResponse({"error": "Expected a JSON object."}, status=400)
    return body, None


def _save_position_fields(obj, body, max_size):
    try:
        if "x" in body or "y" in body:
            x, y = body.get("x", getattr(obj, "x", 50)), body.get("y", getattr(obj, "y", 50))
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (x, y)):
                raise ValueError
            if not 0 <= x <= 100 or not 0 <= y <= 100:
                raise ValueError
            obj.x, obj.y = x, y
        for field in ("width_percent", "height_percent", "rotation"):
            if field in body:
                value = body[field]
                if value is None and field in ("width_percent", "height_percent"):
                    setattr(obj, field, None)
                    continue
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError
                if field == "rotation":
                    if not 0 <= value <= 359:
                        raise ValueError
                elif not 3 <= value <= max_size:
                    raise ValueError
                setattr(obj, field, value)
        if hasattr(obj, "name") and "name" in body:
            name_val = str(body["name"]).strip()
            if 1 <= len(name_val) <= 20:
                obj.name = name_val
        if hasattr(obj, "section") and "section" in body:
            obj.section = str(body["section"]).strip()[:40]
        if hasattr(obj, "seats") and "seats" in body:
            seats_val = int(body["seats"])
            if 1 <= seats_val <= 30:
                obj.seats = seats_val
        if hasattr(obj, "min_seats") and "min_seats" in body:
            min_seats_val = int(body["min_seats"])
            if 1 <= min_seats_val <= 30:
                obj.min_seats = min_seats_val
        if hasattr(obj, "shape") and "shape" in body:
            if body["shape"] in {"square", "rect", "long", "banquet", "round"}:
                obj.shape = body["shape"]
        if hasattr(obj, "status") and "status" in body:
            if body["status"] in {"available", "occupied", "unavailable"}:
                obj.status = body["status"]
        if hasattr(obj, "label") and "label" in body:
            label_val = str(body["label"]).strip()
            if 1 <= len(label_val) <= 60:
                obj.label = label_val
        if hasattr(obj, "kind") and "kind" in body:
            if any(k[0] == body["kind"] for k in FLOOR_ELEMENT_KINDS):
                obj.kind = body["kind"]
    except (KeyError, ValueError):
        return False
    return True


@dash_only
@require_POST
def d_table_position(request, rests, is_admin, pk):
    body, error = _json_body(request)
    if error:
        return error
    table = get_object_or_404(Table, pk=pk, restaurant__in=rests)
    if not _save_position_fields(table, body, 40):
        return JsonResponse({"error": "Invalid table position or dimensions."}, status=400)
    table.save()
    return JsonResponse({
        "saved": True,
        "table": {
            "id": table.pk,
            "name": table.name,
            "section": table.section,
            "seats": table.seats,
            "min_seats": table.min_seats,
            "shape": table.shape,
            "x": table.x,
            "y": table.y,
            "width_percent": table.width_percent,
            "height_percent": table.height_percent,
            "rotation": table.rotation,
            "status": table.status,
            "position_url": reverse("d_table_position", args=[table.pk]),
        }
    })


@dash_only
@require_POST
def d_table_create(request, rests, is_admin):
    body, error = _json_body(request)
    if error:
        return error
    restaurant = rests.filter(slug=body.get("restaurant")).first()
    if not restaurant:
        return JsonResponse({"error": "Restaurant not found."}, status=404)
    name = str(body.get("name") or "").strip()[:20]
    if not name:
        existing_count = restaurant.table_set.count() + 1
        name = f"Table {existing_count}"
    shape = body.get("shape", "square")
    if shape not in {"square", "rect", "long", "banquet", "round"}:
        shape = "square"
    seats = int(body.get("seats") or 4)
    min_seats = int(body.get("min_seats") or 1)
    section = str(body.get("section") or "Dining Room").strip()[:40]
    x = int(body.get("x") if body.get("x") is not None else 50)
    y = int(body.get("y") if body.get("y") is not None else 50)
    width = _optional_int(body.get("width_percent"))
    height = _optional_int(body.get("height_percent"))
    rotation = int(body.get("rotation") or 0) % 360
    status = body.get("status", "available")
    if status not in {"available", "occupied", "unavailable"}:
        status = "available"

    table = Table.objects.create(
        restaurant=restaurant,
        name=name,
        section=section,
        seats=max(1, min(30, seats)),
        min_seats=max(1, min(30, min_seats)),
        shape=shape,
        x=max(0, min(100, x)),
        y=max(0, min(100, y)),
        width_percent=width if width and 3 <= width <= 40 else None,
        height_percent=height if height and 3 <= height <= 40 else None,
        rotation=rotation,
        status=status,
    )
    return JsonResponse({
        "saved": True,
        "table": {
            "id": table.pk,
            "name": table.name,
            "section": table.section,
            "seats": table.seats,
            "min_seats": table.min_seats,
            "shape": table.shape,
            "x": table.x,
            "y": table.y,
            "width_percent": table.width_percent,
            "height_percent": table.height_percent,
            "rotation": table.rotation,
            "status": table.status,
            "position_url": reverse("d_table_position", args=[table.pk]),
        }
    })


@dash_only
@require_POST
def d_table_duplicate(request, rests, is_admin, pk):
    original = get_object_or_404(Table, pk=pk, restaurant__in=rests)
    base_name = original.name
    import re
    match = re.search(r"\d+", base_name)
    if match:
        num = int(match.group())
        new_name = base_name[:match.start()] + str(num + 1) + base_name[match.end():]
    else:
        new_name = f"{base_name} Copy"
    new_name = new_name[:20]

    new_x = min(92, original.x + 5)
    new_y = min(92, original.y + 5)

    clone = Table.objects.create(
        restaurant=original.restaurant,
        name=new_name,
        section=original.section,
        seats=original.seats,
        min_seats=original.min_seats,
        shape=original.shape,
        x=new_x,
        y=new_y,
        width_percent=original.width_percent,
        height_percent=original.height_percent,
        rotation=original.rotation,
        status=original.status,
    )
    return JsonResponse({
        "saved": True,
        "table": {
            "id": clone.pk,
            "name": clone.name,
            "section": clone.section,
            "seats": clone.seats,
            "min_seats": clone.min_seats,
            "shape": clone.shape,
            "x": clone.x,
            "y": clone.y,
            "width_percent": clone.width_percent,
            "height_percent": clone.height_percent,
            "rotation": clone.rotation,
            "status": clone.status,
            "position_url": reverse("d_table_position", args=[clone.pk]),
        }
    })


@dash_only
@require_POST
def d_table_delete(request, rests, is_admin, pk):
    table = get_object_or_404(Table, pk=pk, restaurant__in=rests)
    table_id = table.pk
    table.delete()
    return JsonResponse({"deleted": True, "id": table_id})


@dash_only
@require_POST
def d_element_position(request, rests, is_admin, pk):
    body, error = _json_body(request)
    if error:
        return error
    element = get_object_or_404(FloorPlanElement, pk=pk, restaurant__in=rests)
    if not _save_position_fields(element, body, 100):
        return JsonResponse({"error": "Invalid floor element position or dimensions."}, status=400)
    element.save()
    return JsonResponse({
        "saved": True,
        "element": {
            "id": element.pk,
            "kind": element.kind,
            "label": element.label,
            "x": element.x,
            "y": element.y,
            "width_percent": element.width_percent,
            "height_percent": element.height_percent,
            "rotation": element.rotation,
            "position_url": reverse("d_element_position", args=[element.pk]),
        }
    })


@dash_only
@require_POST
def d_element_create(request, rests, is_admin):
    body, error = _json_body(request)
    if error:
        return error
    restaurant = rests.filter(slug=body.get("restaurant")).first()
    if not restaurant:
        return JsonResponse({"error": "Restaurant not found."}, status=404)
    kind = body.get("kind", "wall")
    if kind == "bar":
        default_label = "Bar"
        default_w, default_h = 5, 45
    elif kind == "counter":
        default_label = "Counter"
        default_w, default_h = 18, 8
    elif kind == "window":
        default_label = "Window"
        default_w, default_h = 14, 4
    elif kind == "entrance":
        default_label = "Entrance"
        default_w, default_h = 12, 6
    else:
        default_label = kind.capitalize()
        default_w, default_h = 14, 12

    label = str(body.get("label") or default_label)[:60]
    x = int(body.get("x") if body.get("x") is not None else 50)
    y = int(body.get("y") if body.get("y") is not None else 50)
    width = int(body.get("width_percent") or default_w)
    height = int(body.get("height_percent") or default_h)
    rotation = int(body.get("rotation") or 0) % 360

    element = FloorPlanElement.objects.create(
        restaurant=restaurant,
        kind=kind,
        label=label,
        x=max(0, min(100, x)),
        y=max(0, min(100, y)),
        width_percent=max(3, min(100, width)),
        height_percent=max(3, min(100, height)),
        rotation=rotation,
    )
    return JsonResponse({
        "saved": True,
        "element": {
            "id": element.pk,
            "kind": element.kind,
            "label": element.label,
            "x": element.x,
            "y": element.y,
            "width_percent": element.width_percent,
            "height_percent": element.height_percent,
            "rotation": element.rotation,
            "position_url": reverse("d_element_position", args=[element.pk]),
        }
    })


@dash_only
@require_POST
def d_element_delete(request, rests, is_admin, pk):
    element = get_object_or_404(FloorPlanElement, pk=pk, restaurant__in=rests)
    element_id = element.pk
    element.delete()
    return JsonResponse({"deleted": True, "id": element_id})


@dash_only
@require_POST
def d_floor_orientation(request, rests, is_admin):
    body, error = _json_body(request)
    if error:
        return error
    restaurant = rests.filter(slug=body.get("restaurant")).first()
    if not restaurant:
        return JsonResponse({"error": "Restaurant not found."}, status=404)
    orientation = str(body.get("orientation") or "landscape").lower()
    w, h = float(restaurant.floor_width), float(restaurant.floor_height)
    if orientation == "landscape" and w < h:
        restaurant.floor_width, restaurant.floor_height = h, w
        restaurant.save(update_fields=["floor_width", "floor_height"])
    elif orientation == "portrait" and h < w:
        restaurant.floor_width, restaurant.floor_height = h, w
        restaurant.save(update_fields=["floor_width", "floor_height"])
    return JsonResponse({
        "saved": True,
        "orientation": orientation,
        "floor_width": float(restaurant.floor_width),
        "floor_height": float(restaurant.floor_height),
    })


@dash_only
@require_POST
def d_floor_batch_save(request, rests, is_admin):
    body, error = _json_body(request)
    if error:
        return error
    restaurant = rests.filter(slug=body.get("restaurant")).first()
    if not restaurant:
        return JsonResponse({"error": "Restaurant not found."}, status=404)
    tables_data = body.get("tables", [])
    for t_data in tables_data:
        pk = t_data.get("id")
        table = restaurant.table_set.filter(pk=pk).first()
        if table:
            _save_position_fields(table, t_data, 40)
            table.save()
    elements_data = body.get("elements", [])
    for e_data in elements_data:
        pk = e_data.get("id")
        element = restaurant.floor_elements.filter(pk=pk).first()
        if element:
            _save_position_fields(element, e_data, 100)
            element.save()
    return JsonResponse({"saved": True})


@dash_only
@require_POST
def d_floor_outline(request, rests, is_admin):
    body, error = _json_body(request)
    if error:
        return error
    restaurant = rests.filter(slug=body.get("restaurant")).first()
    if restaurant is None:
        return JsonResponse({"error": "Restaurant not found."}, status=404)
    points = body.get("points")
    if not isinstance(points, list) or len(points) < 3:
        return JsonResponse({"error": "A floor boundary needs at least three points."}, status=400)
    normalized = []
    try:
        for point in points:
            x, y = point["x"], point["y"]
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (x, y)):
                raise ValueError
            if not 0 <= x <= 100 or not 0 <= y <= 100:
                raise ValueError
            normalized.append({"x": x, "y": y})
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Boundary points must be integer percentages from 0 to 100."}, status=400)
    area = sum(
        point["x"] * normalized[(index + 1) % len(normalized)]["y"]
        - normalized[(index + 1) % len(normalized)]["x"] * point["y"]
        for index, point in enumerate(normalized)
    )
    if area == 0:
        return JsonResponse({"error": "The boundary points must form an area."}, status=400)
    restaurant.floor_outline = normalized
    restaurant.save(update_fields=["floor_outline"])
    return JsonResponse({"saved": True})


@dash_only
def d_customers(request, rests, is_admin):
    if not is_admin:
        raise PermissionDenied
    users = (User.objects.annotate(n=Count("reservation"))
             .select_related("manager__restaurant").order_by("-date_joined"))
    role_groups = [
        {"slug": "administrators", "title": "Administrators", "description": "Full dashboard and account access.",
         "users": users.filter(is_staff=True)},
        {"slug": "managers", "title": "Restaurant managers", "description": "Restaurant-specific management access.",
         "users": users.filter(is_staff=False, manager__isnull=False)},
        {"slug": "customers", "title": "Customers", "description": "Registered booking accounts.",
         "users": users.filter(is_staff=False, manager__isnull=True)},
    ]
    return dash(request, "d_accounts.html", is_admin, "accounts", role_groups=role_groups,
                account_total=users.count())
