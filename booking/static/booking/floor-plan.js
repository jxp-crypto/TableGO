(() => {
  const plan = document.querySelector(".plan[data-editable='true']");
  if (!plan) return;

  const status = document.querySelector("[data-floor-status]");
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
  const outlineToggle = document.querySelector("[data-outline-toggle]");
  const outlineSave = document.querySelector("[data-outline-save]");
  const rotateLegacyBtn = document.querySelector("[data-rotate-selected]");

  // Top Bar elements
  const btnCancel = document.querySelector("[data-editor-cancel]");
  const btnSave = document.querySelector("[data-editor-save]");
  const orientButtons = document.querySelectorAll(".orient-btn");

  // Inspector panel elements
  const inspectorForm = document.getElementById("inspector-form");
  const noSelectionMsg = document.getElementById("inspector-no-selection");
  const propName = document.getElementById("prop-name");
  const propSection = document.getElementById("prop-section");
  const propSectionCustom = document.getElementById("prop-section-custom");
  const propMinSeats = document.getElementById("prop-min-seats");
  const propMaxSeats = document.getElementById("prop-max-seats");
  const propWidth = document.getElementById("prop-width");
  const propHeight = document.getElementById("prop-height");
  const aspectLockBtn = document.getElementById("aspect-lock-toggle");
  const rotationDisplayVal = document.getElementById("rotation-display-val");
  const btnRotateCCW = document.getElementById("btn-rotate-ccw");
  const btnRotateCW = document.getElementById("btn-rotate-cw");
  const propShape = document.getElementById("prop-shape");
  const propStatus = document.getElementById("prop-status");
  const propKind = document.getElementById("prop-kind");
  const tableOnlyFields = document.querySelectorAll(".table-only-prop");
  const elementOnlyFields = document.querySelectorAll(".element-only-prop");

  // Action buttons
  const btnDuplicate = document.getElementById("btn-action-duplicate");
  const btnDelete = document.getElementById("btn-action-delete");

  // Grid snap checkbox
  const gridSnapCheck = document.getElementById("grid-snap-check");

  let selected = null;
  let drawing = false;
  let points = [];
  let drag = null;
  let isAspectLocked = true;
  let debounceTimer = null;

  const setStatus = (message, isError = false) => {
    if (!status) return;
    status.textContent = message;
    const banner = document.querySelector(".editor-status-banner");
    if (banner) {
      banner.classList.toggle("has-error", isError);
      banner.classList.toggle("has-success", !isError);
    }
  };

  // Helper to snap to grid if enabled (default grid step 2.5%)
  const snap = (val, step = 2.5) => {
    if (!gridSnapCheck || !gridSnapCheck.checked) return Math.round(val);
    return Math.round(val / step) * step;
  };

  const save = async (node, values) => {
    if (!node || !node.dataset.positionUrl) return;
    const response = await fetch(node.dataset.positionUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify(values),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not save this floor-plan change.");
    setStatus("Floor-plan change saved.");
    return result;
  };

  const position = (node) => ({
    x: Math.round(parseFloat(node.style.left) || 0),
    y: Math.round(parseFloat(node.style.top) || 0),
  });

  const resizeValues = (node) => {
    const bounds = plan.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return { width_percent: 10, height_percent: 10 };
    return {
      width_percent: Math.round((node.offsetWidth / bounds.width) * 100),
      height_percent: Math.round((node.offsetHeight / bounds.height) * 100),
    };
  };

  const hasOverlap = (node) => {
    // We allow administrators to place items naturally according to their blueprint,
    // but check if completely off-grid
    const x = parseFloat(node.style.left);
    const y = parseFloat(node.style.top);
    return x < 0 || x > 100 || y < 0 || y > 100;
  };

  const persistNode = async (node) => {
    const isTable = node.classList.contains("tbl");
    const values = {
      ...position(node),
      ...resizeValues(node),
      rotation: Number(node.dataset.rotation || 0),
    };
    if (isTable) {
      if (node.dataset.name) values.name = node.dataset.name;
      if (node.dataset.section) values.section = node.dataset.section;
      if (node.dataset.seats) values.seats = Number(node.dataset.seats);
      if (node.dataset.minSeats) values.min_seats = Number(node.dataset.minSeats);
      if (node.dataset.shape) values.shape = node.dataset.shape;
      if (node.dataset.status) values.status = node.dataset.status;
    } else {
      if (node.dataset.label) values.label = node.dataset.label;
      if (node.dataset.kind) values.kind = node.dataset.kind;
    }

    try {
      await save(node, values);
      node.dataset.x = values.x;
      node.dataset.y = values.y;
      node.dataset.width = values.width_percent;
      node.dataset.height = values.height_percent;
      node.dataset.rotation = values.rotation;
      return true;
    } catch (error) {
      setStatus(error.message, true);
      return false;
    }
  };

  // Populate the inspector panel based on selected node
  const updateInspector = () => {
    if (!selected) {
      if (inspectorForm) inspectorForm.style.display = "none";
      if (noSelectionMsg) noSelectionMsg.style.display = "block";
      if (btnDuplicate) btnDuplicate.disabled = true;
      if (btnDelete) btnDelete.disabled = true;
      if (rotateLegacyBtn) rotateLegacyBtn.disabled = true;
      return;
    }

    if (inspectorForm) inspectorForm.style.display = "block";
    if (noSelectionMsg) noSelectionMsg.style.display = "none";
    if (btnDuplicate) btnDuplicate.disabled = false;
    if (btnDelete) btnDelete.disabled = false;
    if (rotateLegacyBtn) rotateLegacyBtn.disabled = false;

    const isTable = selected.classList.contains("tbl");
    tableOnlyFields.forEach((el) => {
      el.style.display = isTable ? "" : "none";
    });
    elementOnlyFields.forEach((el) => {
      el.style.display = isTable ? "none" : "";
    });

    if (!isTable && propKind) {
      propKind.value = selected.dataset.kind || "wall";
    }

    // Populate Fields
    if (propName) {
      propName.value = isTable ? (selected.dataset.name || "") : (selected.dataset.label || "");
    }

    if (isTable) {
      if (propSection) {
        const sec = selected.dataset.section || "Dining Room";
        let found = false;
        for (let i = 0; i < propSection.options.length; i++) {
          if (propSection.options[i].value === sec) {
            propSection.selectedIndex = i;
            found = true;
            break;
          }
        }
        if (!found) {
          const opt = new Option(sec, sec, true, true);
          propSection.insertBefore(opt, propSection.lastElementChild);
        }
        if (propSectionCustom) propSectionCustom.style.display = "none";
      }
      if (propMinSeats) propMinSeats.value = selected.dataset.minSeats || 1;
      if (propMaxSeats) propMaxSeats.value = selected.dataset.seats || 4;
      if (propShape) propShape.value = selected.dataset.shape || "square";
      if (propStatus) propStatus.value = selected.dataset.status || "available";
    }

    const bounds = plan.getBoundingClientRect();
    const curW = bounds.width ? Math.round((selected.offsetWidth / bounds.width) * 100) : 10;
    const curH = bounds.height ? Math.round((selected.offsetHeight / bounds.height) * 100) : 10;
    if (propWidth) propWidth.value = selected.dataset.width || curW;
    if (propHeight) propHeight.value = selected.dataset.height || curH;

    const rot = Number(selected.dataset.rotation || 0);
    if (rotationDisplayVal) rotationDisplayVal.textContent = `${rot}°`;
  };

  const selectNode = (node) => {
    if (selected === node) return;
    plan.querySelectorAll(".movable.selected").forEach((item) => item.classList.remove("selected"));
    selected = node;
    if (node) {
      node.classList.add("selected");
      setStatus(`Selected: ${node.dataset.name || node.dataset.label || "Element"}. Drag or use inspector on right.`);
    } else {
      setStatus("No item selected. Click a table to inspect or drag it.");
    }
    updateInspector();
  };

  const rotate = async (degreesDelta) => {
    if (!selected) return;
    const current = Number(selected.dataset.rotation || 0);
    const newRot = (current + degreesDelta + 360) % 360;
    selected.dataset.rotation = newRot;
    selected.style.setProperty("--rotation", `${newRot}deg`);
    if (rotationDisplayVal) rotationDisplayVal.textContent = `${newRot}°`;
    await persistNode(selected);
  };

  // Rotation buttons
  if (btnRotateCCW) {
    btnRotateCCW.addEventListener("click", () => rotate(-15));
  }
  if (btnRotateCW) {
    btnRotateCW.addEventListener("click", () => rotate(15));
  }
  if (rotateLegacyBtn) {
    rotateLegacyBtn.addEventListener("click", () => rotate(15));
  }

  // Aspect ratio lock toggle
  if (aspectLockBtn) {
    aspectLockBtn.addEventListener("click", () => {
      isAspectLocked = !isAspectLocked;
      aspectLockBtn.classList.toggle("locked", isAspectLocked);
      const iconLocked = aspectLockBtn.querySelector(".lock-icon-locked");
      const iconUnlocked = aspectLockBtn.querySelector(".lock-icon-unlocked");
      if (iconLocked) iconLocked.style.display = isAspectLocked ? "" : "none";
      if (iconUnlocked) iconUnlocked.style.display = isAspectLocked ? "none" : "";
      setStatus(isAspectLocked ? "Aspect ratio locked." : "Aspect ratio unlocked.");
    });
  }

  // Inspector form field live updating
  const debouncedSave = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      if (selected) persistNode(selected);
    }, 300);
  };

  if (propName) {
    propName.addEventListener("input", () => {
      if (!selected) return;
      const val = propName.value.trim();
      if (selected.classList.contains("tbl")) {
        selected.dataset.name = val;
        const nameEl = selected.querySelector(".tbl-name");
        if (nameEl) nameEl.textContent = val;
      } else {
        selected.dataset.label = val;
        const labelEl = selected.querySelector(".element-label");
        if (labelEl) labelEl.textContent = val;
      }
      debouncedSave();
    });
  }

  if (propSection) {
    propSection.addEventListener("change", () => {
      if (!selected) return;
      if (propSection.value === "__custom__") {
        if (propSectionCustom) {
          propSectionCustom.style.display = "block";
          propSectionCustom.focus();
        }
        return;
      }
      if (propSectionCustom) propSectionCustom.style.display = "none";
      selected.dataset.section = propSection.value;
      const secEl = selected.querySelector(".tbl-section");
      if (secEl) secEl.textContent = propSection.value;
      debouncedSave();
    });
  }

  if (propSectionCustom) {
    propSectionCustom.addEventListener("input", () => {
      if (!selected) return;
      const val = propSectionCustom.value.trim();
      selected.dataset.section = val;
      const secEl = selected.querySelector(".tbl-section");
      if (secEl) secEl.textContent = val;
      debouncedSave();
    });
  }

  if (propMinSeats) {
    propMinSeats.addEventListener("input", () => {
      if (!selected) return;
      selected.dataset.minSeats = Math.max(1, Math.min(30, parseInt(propMinSeats.value) || 1));
      debouncedSave();
    });
  }

  if (propMaxSeats) {
    propMaxSeats.addEventListener("input", () => {
      if (!selected) return;
      const seats = Math.max(1, Math.min(30, parseInt(propMaxSeats.value) || 1));
      selected.dataset.seats = seats;
      const seatsEl = selected.querySelector(".tbl-seats");
      if (seatsEl) seatsEl.textContent = `${seats} ${seats === 1 ? "Seat" : "Seats"}`;
      debouncedSave();
    });
  }

  if (propWidth) {
    propWidth.addEventListener("input", () => {
      if (!selected) return;
      const w = Math.max(3, Math.min(100, parseInt(propWidth.value) || 10));
      const oldW = parseInt(selected.dataset.width) || parseInt(propWidth.value) || 10;
      const oldH = parseInt(selected.dataset.height) || parseInt(propHeight.value) || 10;
      selected.style.width = `${w}%`;
      selected.dataset.width = w;

      if (isAspectLocked && oldW > 0) {
        const ratio = oldH / oldW;
        const newH = Math.max(3, Math.min(100, Math.round(w * ratio)));
        selected.style.height = `${newH}%`;
        selected.dataset.height = newH;
        if (propHeight) propHeight.value = newH;
      }
      debouncedSave();
    });
  }

  if (propHeight) {
    propHeight.addEventListener("input", () => {
      if (!selected) return;
      const h = Math.max(3, Math.min(100, parseInt(propHeight.value) || 10));
      const oldW = parseInt(selected.dataset.width) || parseInt(propWidth.value) || 10;
      const oldH = parseInt(selected.dataset.height) || parseInt(propHeight.value) || 10;
      selected.style.height = `${h}%`;
      selected.dataset.height = h;

      if (isAspectLocked && oldH > 0) {
        const ratio = oldW / oldH;
        const newW = Math.max(3, Math.min(100, Math.round(h * ratio)));
        selected.style.width = `${newW}%`;
        selected.dataset.width = newW;
        if (propWidth) propWidth.value = newW;
      }
      debouncedSave();
    });
  }

  if (propShape) {
    propShape.addEventListener("change", () => {
      if (!selected || !selected.classList.contains("tbl")) return;
      const shapes = ["square", "rect", "long", "banquet", "round"];
      shapes.forEach((s) => selected.classList.remove(s));
      selected.classList.add(propShape.value);
      selected.dataset.shape = propShape.value;
      debouncedSave();
    });
  }

  if (propStatus) {
    propStatus.addEventListener("change", () => {
      if (!selected || !selected.classList.contains("tbl")) return;
      const statuses = ["available", "occupied", "unavailable"];
      statuses.forEach((s) => selected.classList.remove(s));
      selected.classList.add(propStatus.value);
      selected.dataset.status = propStatus.value;
      debouncedSave();
    });
  }

  if (propKind) {
    propKind.addEventListener("change", () => {
      if (!selected || selected.classList.contains("tbl")) return;
      const kinds = [
        "window", "entrance", "counter", "bar", "wall", "zone",
        "reception", "kitchen", "restroom", "partition", "exit"
      ];
      kinds.forEach((k) => selected.classList.remove(`element-${k}`));
      selected.classList.add(`element-${propKind.value}`);
      selected.dataset.kind = propKind.value;
      debouncedSave();
    });
  }

  // Pointer interaction on canvas (Dragging, Resizing, Selection)
  plan.addEventListener("pointerdown", (event) => {
    if (drawing && event.target === plan) {
      const bounds = plan.getBoundingClientRect();
      points.push({
        x: Math.round(((event.clientX - bounds.left) / bounds.width) * 100),
        y: Math.round(((event.clientY - bounds.top) / bounds.height) * 100),
      });
      plan.classList.add("drawing-outline");
      plan.querySelector(".floor-boundary-preview").innerHTML =
        `<polygon points="${points.map((p) => `${p.x},${p.y}`).join(" ")}"></polygon>`;
      if (outlineSave) outlineSave.disabled = points.length < 3;
      setStatus(`${points.length} boundary points. Add at least three, then save.`);
      return;
    }

    const node = event.target.closest(".movable");
    if (!node || drawing) {
      if (event.target === plan) selectNode(null);
      return;
    }

    event.preventDefault();
    selectNode(node);

    const resizing = event.target.closest(".resize-handle") !== null;
    const original = {
      left: node.style.left,
      top: node.style.top,
      width: node.style.width,
      height: node.style.height,
    };

    drag = {
      node,
      pointerX: event.clientX,
      pointerY: event.clientY,
      startX: parseFloat(node.style.left) || 0,
      startY: parseFloat(node.style.top) || 0,
      startWidth: (node.offsetWidth / plan.clientWidth) * 100,
      startHeight: (node.offsetHeight / plan.clientHeight) * 100,
      resizing,
      original,
    };

    node.setPointerCapture(event.pointerId);
  });

  plan.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const bounds = plan.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;

    if (drag.resizing) {
      const max = drag.node.classList.contains("tbl") ? 40 : 100;
      let width = Math.max(3, Math.min(max, drag.startWidth + ((event.clientX - drag.pointerX) / bounds.width) * 100));
      let height = Math.max(3, Math.min(max, drag.startHeight + ((event.clientY - drag.pointerY) / bounds.height) * 100));
      if (isAspectLocked && drag.startWidth > 0) {
        const ratio = drag.startHeight / drag.startWidth;
        height = Math.max(3, Math.min(max, width * ratio));
      }
      drag.node.style.width = `${Math.round(width)}%`;
      drag.node.style.height = `${Math.round(height)}%`;
      if (propWidth) propWidth.value = Math.round(width);
      if (propHeight) propHeight.value = Math.round(height);
    } else {
      const rawX = drag.startX + ((event.clientX - drag.pointerX) / bounds.width) * 100;
      const rawY = drag.startY + ((event.clientY - drag.pointerY) / bounds.height) * 100;
      const x = Math.max(0, Math.min(100, snap(rawX)));
      const y = Math.max(0, Math.min(100, snap(rawY)));
      drag.node.style.left = `${x}%`;
      drag.node.style.top = `${y}%`;
    }
  });

  plan.addEventListener("pointerup", async () => {
    if (!drag) return;
    const { node, original } = drag;
    drag = null;
    if (hasOverlap(node)) {
      Object.assign(node.style, original);
      setStatus("Position was out of bounds. The change was not saved.", true);
      return;
    }
    const success = await persistNode(node);
    if (!success) Object.assign(node.style, original);
    updateInspector();
  });

  // Keyboard navigation & shortcuts
  document.addEventListener("keydown", async (event) => {
    // Ignore keystrokes if typing inside an input or select
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;

    if (!selected) return;

    let { x, y } = position(selected);
    const amount = event.shiftKey ? 5 : 1;
    const original = { left: selected.style.left, top: selected.style.top };

    if (event.key === "ArrowLeft") x -= amount;
    else if (event.key === "ArrowRight") x += amount;
    else if (event.key === "ArrowUp") y -= amount;
    else if (event.key === "ArrowDown") y += amount;
    else if (event.key.toLowerCase() === "r") {
      event.preventDefault();
      await rotate(event.shiftKey ? -15 : 15);
      return;
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      if (btnDelete && !btnDelete.disabled) btnDelete.click();
      return;
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") {
      event.preventDefault();
      if (btnDuplicate && !btnDuplicate.disabled) btnDuplicate.click();
      return;
    } else {
      return;
    }

    event.preventDefault();
    selected.style.left = `${Math.max(0, Math.min(100, x))}%`;
    selected.style.top = `${Math.max(0, Math.min(100, y))}%`;
    if (!hasOverlap(selected)) {
      const success = await persistNode(selected);
      if (!success) Object.assign(selected.style, original);
    } else {
      Object.assign(selected.style, original);
    }
  });

  // Duplication action
  if (btnDuplicate) {
    btnDuplicate.addEventListener("click", async () => {
      if (!selected) return;
      const dupUrl = selected.dataset.duplicateUrl;
      if (!dupUrl) {
        setStatus("Cannot duplicate this item.", true);
        return;
      }

      setStatus("Duplicating item...");
      try {
        const response = await fetch(dupUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
          },
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Duplication failed.");

        // Reload page or create DOM element
        window.location.reload();
      } catch (err) {
        setStatus(err.message, true);
      }
    });
  }

  // Delete action
  if (btnDelete) {
    btnDelete.addEventListener("click", async () => {
      if (!selected) return;
      const delUrl = selected.dataset.deleteUrl;
      if (!delUrl) {
        setStatus("Cannot delete this item.", true);
        return;
      }

      const name = selected.dataset.name || selected.dataset.label || "item";
      if (!confirm(`Are you sure you want to delete ${name}?`)) return;

      setStatus(`Deleting ${name}...`);
      try {
        const response = await fetch(delUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
          },
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Deletion failed.");

        selected.remove();
        selectNode(null);
        setStatus(`${name} was deleted successfully.`);
      } catch (err) {
        setStatus(err.message, true);
      }
    });
  }

  // Add Table Chip buttons
  document.querySelectorAll("[data-add-table]").forEach((chip) => {
    chip.addEventListener("click", async () => {
      const shape = chip.dataset.addTable || "square";
      const seats = parseInt(chip.dataset.seats) || 4;
      const createUrl = plan.dataset.createTableUrl;
      const restaurant = plan.dataset.restaurant;

      if (!createUrl || !restaurant) return;

      setStatus(`Creating ${shape} table (${seats} seats)...`);
      try {
        const response = await fetch(createUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
          },
          body: JSON.stringify({
            restaurant,
            shape,
            seats,
            min_seats: seats >= 4 ? 2 : 1,
            section: "Dining Room",
            x: 50,
            y: 50,
            width_percent: shape === "banquet" ? 28 : (shape === "rect" || shape === "long" ? 14 : 8),
            height_percent: shape === "rect" || shape === "long" ? 10 : 8,
          }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not create table.");

        window.location.reload();
      } catch (err) {
        setStatus(err.message, true);
      }
    });
  });

  // Add Structure Chip buttons
  document.querySelectorAll("[data-add-element]").forEach((chip) => {
    chip.addEventListener("click", async () => {
      const kind = chip.dataset.addElement || "wall";
      const createUrl = plan.dataset.createElementUrl;
      const restaurant = plan.dataset.restaurant;

      if (!createUrl || !restaurant) return;

      let label = "Structure";
      let width_percent = 14;
      let height_percent = 12;

      if (kind === "window") {
        label = "Window";
        width_percent = 14;
        height_percent = 4;
      } else if (kind === "entrance") {
        label = "Entrance";
        width_percent = 12;
        height_percent = 6;
      } else if (kind === "counter") {
        label = "Counter";
        width_percent = 18;
        height_percent = 8;
      } else if (kind === "bar") {
        label = "Bar";
        width_percent = 5;
        height_percent = 45;
      } else if (kind === "wall") {
        label = "Wall";
        width_percent = 14;
        height_percent = 4;
      } else if (kind === "zone") {
        label = "Zone";
        width_percent = 20;
        height_percent = 15;
      }

      setStatus(`Creating ${label}...`);
      try {
        const response = await fetch(createUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
          },
          body: JSON.stringify({
            restaurant,
            kind,
            label,
            x: 50,
            y: 50,
            width_percent,
            height_percent,
          }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not create element.");

        window.location.reload();
      } catch (err) {
        setStatus(err.message, true);
      }
    });
  });

  // Orientation Buttons (Landscape / Portrait)
  orientButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const orient = btn.dataset.orient;
      const orientUrl = plan.dataset.orientationUrl;
      const restaurant = plan.dataset.restaurant;

      if (!orient || !orientUrl || !restaurant) return;

      orientButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      setStatus(`Setting orientation to ${orient}...`);
      try {
        const response = await fetch(orientUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
          },
          body: JSON.stringify({ restaurant, orientation: orient }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not update orientation.");

        if (result.floor_width && result.floor_height) {
          plan.style.aspectRatio = `${result.floor_width} / ${result.floor_height}`;
        }
        setStatus(`Floor orientation set to ${orient}.`);
      } catch (err) {
        setStatus(err.message, true);
      }
    });
  });

  // Top Bar Save Button
  if (btnSave) {
    btnSave.addEventListener("click", async () => {
      const batchUrl = plan.dataset.batchSaveUrl;
      const restaurant = plan.dataset.restaurant;
      if (!batchUrl || !restaurant) {
        setStatus("All changes are already saved.");
        return;
      }

      setStatus("Saving complete floor layout...");
      const tables = [];
      plan.querySelectorAll(".tbl").forEach((tbl) => {
        tables.push({
          id: parseInt(tbl.dataset.id),
          x: Math.round(parseFloat(tbl.style.left)),
          y: Math.round(parseFloat(tbl.style.top)),
          width_percent: parseInt(tbl.dataset.width) || null,
          height_percent: parseInt(tbl.dataset.height) || null,
          rotation: parseInt(tbl.dataset.rotation) || 0,
          name: tbl.dataset.name,
          section: tbl.dataset.section,
          min_seats: parseInt(tbl.dataset.minSeats) || 1,
          seats: parseInt(tbl.dataset.seats) || 4,
          shape: tbl.dataset.shape || "square",
          status: tbl.dataset.status || "available",
        });
      });

      const elements = [];
      plan.querySelectorAll(".floor-element").forEach((el) => {
        elements.push({
          id: parseInt(el.dataset.id),
          x: Math.round(parseFloat(el.style.left)),
          y: Math.round(parseFloat(el.style.top)),
          width_percent: parseInt(el.dataset.width) || 10,
          height_percent: parseInt(el.dataset.height) || 10,
          rotation: parseInt(el.dataset.rotation) || 0,
          label: el.dataset.label,
          kind: el.dataset.kind,
        });
      });

      try {
        const response = await fetch(batchUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
          },
          body: JSON.stringify({ restaurant, tables, elements }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Batch save failed.");
        setStatus("Restaurant structure and tables saved successfully!");
      } catch (err) {
        setStatus(err.message, true);
      }
    });
  }

  // Top Bar Cancel Button
  if (btnCancel) {
    btnCancel.addEventListener("click", () => {
      if (confirm("Reset any unsaved arrangements?")) {
        window.location.reload();
      }
    });
  }

  // Accordion Expand/Collapse Toggles
  document.querySelectorAll("[data-accordion]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = btn.closest(".accordion-item");
      const isExpanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!isExpanded));
      item.classList.toggle("open", !isExpanded);
      const chevron = btn.querySelector(".accordion-chevron");
      if (chevron) {
        chevron.className = isExpanded ? "ri-arrow-right-s-line accordion-chevron" : "ri-arrow-down-s-line accordion-chevron";
      }
      const body = item.querySelector(".accordion-body");
      if (body) {
        body.style.display = isExpanded ? "none" : "block";
      }
    });
  });

  // Alignment Tools
  document.querySelectorAll("[data-align]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!selected) return;
      const type = btn.dataset.align;
      if (type === "left") selected.style.left = "10%";
      else if (type === "center") selected.style.left = "50%";
      else if (type === "right") selected.style.left = "90%";
      else if (type === "top") selected.style.top = "10%";
      else if (type === "middle") selected.style.top = "50%";
      else if (type === "bottom") selected.style.top = "90%";
      await persistNode(selected);
      updateInspector();
      setStatus(`Aligned item to ${type}.`);
    });
  });

  // Boundary Drawing (Legacy feature support)
  if (outlineToggle) {
    outlineToggle.addEventListener("click", () => {
      drawing = !drawing;
      points = [];
      plan.classList.toggle("drawing-outline", drawing);
      if (outlineSave) outlineSave.disabled = true;
      if (drawing) plan.scrollIntoView({ block: "center" });
      setStatus(
        drawing
          ? "Click around the floor perimeter to draw its irregular outline."
          : "Boundary drawing cancelled."
      );
    });
  }

  if (outlineSave) {
    outlineSave.addEventListener("click", async () => {
      const response = await fetch(plan.dataset.outlineUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf,
        },
        body: JSON.stringify({ restaurant: plan.dataset.restaurant, points }),
      });
      const result = await response.json();
      if (!response.ok) {
        setStatus(result.error || "Could not save the floor boundary.", true);
        return;
      }
      window.location.reload();
    });
  }
})();