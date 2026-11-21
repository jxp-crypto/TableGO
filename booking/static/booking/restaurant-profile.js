(() => {
  window.gm_authFailure = () => {
    const status = document.querySelector("[data-map-status]");
    if (status) status.textContent = "Google Maps could not authenticate. Check the API key and its referrer restrictions.";
  };

  const imageInput = document.querySelector("#id_image");
  const imagePreview = document.querySelector("[data-image-preview]");
  if (imageInput && imagePreview) {
    imageInput.addEventListener("change", () => {
      const file = imageInput.files[0];
      if (!file) return;
      const previewUrl = URL.createObjectURL(file);
      imagePreview.src = previewUrl;
      imagePreview.onload = () => URL.revokeObjectURL(previewUrl);
    });
  }

  window.initRestaurantMap = () => {
    const canvas = document.querySelector("[data-map-canvas]");
    const status = document.querySelector("[data-map-status]");
    const latInput = document.querySelector("#id_latitude");
    const lngInput = document.querySelector("#id_longitude");
    const locationInput = document.querySelector("#id_location");
    const searchInput = document.querySelector("[data-map-search]");
    if (!canvas || !latInput || !lngInput) return;

    const hasCoordinates = latInput.value !== "" && lngInput.value !== "";
    const center = hasCoordinates
      ? { lat: Number(latInput.value), lng: Number(lngInput.value) }
      : { lat: 12.8797, lng: 121.7740 };
    const map = new google.maps.Map(canvas, {
      center,
      zoom: hasCoordinates ? 16 : 6,
      mapTypeControl: false,
      streetViewControl: false,
    });
    const marker = new google.maps.Marker({
      map,
      position: hasCoordinates ? center : null,
      draggable: true,
    });

    const setCoordinates = (location) => {
      const lat = location.lat();
      const lng = location.lng();
      latInput.value = lat.toFixed(6);
      lngInput.value = lng.toFixed(6);
      marker.setPosition(location);
      map.panTo(location);
      map.setZoom(16);
      status.textContent = `Pinned at ${lat.toFixed(6)}, ${lng.toFixed(6)}.`;
    };

    map.addListener("click", (event) => setCoordinates(event.latLng));
    marker.addListener("dragend", (event) => setCoordinates(event.latLng));

    if (searchInput && google.maps.places) {
      const autocomplete = new google.maps.places.Autocomplete(searchInput, {
        fields: ["formatted_address", "geometry", "name"],
      });
      autocomplete.addListener("place_changed", () => {
        const place = autocomplete.getPlace();
        if (!place.geometry || !place.geometry.location) {
          status.textContent = "Choose a suggested result to pin its location.";
          return;
        }
        if (locationInput) {
          locationInput.value = place.formatted_address || place.name || locationInput.value;
        }
        setCoordinates(place.geometry.location);
      });
    }
  };
})();
