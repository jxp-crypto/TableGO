# TableGO

TableGO is a Django restaurant reservation and table-management application.

## Local setup (Windows PowerShell)

Run commands from the repository root. If the virtual environment is not already active:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DEBUG_MODE = "true"
$env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1"
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/` (the Django development server does not provide HTTPS). With `DEBUG_MODE=true`, verification emails are printed to the runserver console.

Before applying migrations to an existing installation, back up its database. For SQLite:

```powershell
Copy-Item .\db.sqlite3 .\db.sqlite3.backup
python manage.py migrate
```

The migrations add reservation schedule/duration fields, floor-plan configuration, restaurant image/location fields, email verification, and table statuses. Existing reservations, restaurant records, fixtures, and table positions are retained. Existing reservation end times are backfilled using a two-hour duration; existing restaurant opening hours are parsed when possible.

## Feature configuration

### Reservation schedule

Administrators can set restaurant opening/closing times, the arrival-time interval, default reservation duration, and floor dimensions in Restaurant Management. Customers choose a preset or a custom duration in 30-minute increments. A reservation is created only after its email code is verified; table availability is checked again at that point.

### Google Maps

Set `GOOGLE_MAPS_API_KEY` in the process environment to enable the restaurant location picker. Enable the Google Maps JavaScript API and Places API for the key. Google’s browser API key is necessarily sent to the browser on the administrator location form; restrict it by HTTP referrer and allowed API. Do not commit the key. Customer map previews and directions links use the saved coordinates.

### Email verification

For production SMTP, configure these environment variables:

```text
EMAIL_HOST
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
EMAIL_HOST_USER
EMAIL_HOST_PASSWORD
DEFAULT_FROM_EMAIL
```

The application defaults to Django’s console email backend in debug mode and SMTP otherwise. Verification codes expire after 10 minutes, are stored hashed, allow at most five attempts, and have resend/request rate limits. Confirmation messages are sent after successful verification.

### Restaurant images and media

Restaurant image uploads accept JPG/JPEG, PNG, and WEBP, up to 5 MB and 20 megapixels. The app verifies image contents and generates storage filenames. During development, uploads are stored under `media/` and served by Django only when `DEBUG_MODE=true`. In production, configure persistent media storage and serve `MEDIA_URL` through a web server or object-storage backend; do not rely on Django’s development media serving.

### Floor plans and drag-and-drop editor

In Dashboard → Table Management, administrators and managers can freely arrange tables and structural elements to match the actual restaurant architecture rather than selecting from predefined positions:
- **Canvas & Orientation**: Toggle between Landscape and Portrait orientation to fit room dimensions; items snap cleanly to the architectural grid.
- **Palette**: Quickly add square, rectangular, round, bar stool, and banquet tables, as well as structural elements like bar counters, walls, and dining zones.
- **Drag & Resize**: Drag tables or room elements across the floor; resize using corner handles or width/height inputs with optional aspect ratio lock.
- **Inspector Panel**: Edit table name, section (e.g. Dining Room, Patio, Bar), minimum and maximum seats, shape, and status.
- **Rotation Controls**: Rotate items clockwise or counter-clockwise using the inspector's dedicated rotation buttons (`↶` and `↷`), press **R** (or **Shift+R**), or use keyboard arrow keys for fine positioning.
- **Actions**: Duplicate any selected table or structure with one click, delete with confirmation, and save or revert layout changes. Custom boundary polygon drawing is also supported.

## Validation

```powershell
$env:DEBUG_MODE = "true"
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test booking.tests
```

Apply migrations before starting a deployment and collect static assets with `python manage.py collectstatic --noinput`. Keep `DEBUG_MODE=false`, set `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`, and use a production WSGI/ASGI server with HTTPS termination.
