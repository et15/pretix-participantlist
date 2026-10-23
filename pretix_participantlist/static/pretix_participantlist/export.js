/* Export page: copy a list kind into the "Custom list" fields, and hide
 * those fields while another list kind is selected. */
(function () {
    "use strict";

    var CUSTOM_VALUE = "__custom__";
    var CUSTOM_FIELDS = [
        "custom_name", "custom_columns", "custom_sort",
        "custom_include_pending", "custom_save"
    ];

    function named(form, name) {
        return form.querySelector('[name="' + name + '"], [name$="-' + name + '"]');
    }

    function listInputs(form) {
        return form.querySelectorAll('[name="list"], [name$="-list"]');
    }

    function selectedKind(form) {
        var inputs = listInputs(form);
        for (var i = 0; i < inputs.length; i++) {
            var input = inputs[i];
            if (input.tagName === "SELECT") {
                return input.value;
            }
            if (input.checked) {
                return input.value;
            }
        }
        return "";
    }

    function selectCustom(form) {
        var inputs = listInputs(form);
        for (var i = 0; i < inputs.length; i++) {
            var input = inputs[i];
            if (input.tagName === "SELECT") {
                input.value = CUSTOM_VALUE;
            } else if (input.value === CUSTOM_VALUE) {
                input.checked = true;
            } else {
                continue;
            }
            input.dispatchEvent(new Event("change", {bubbles: true}));
        }
    }

    function syncCustomFields(form) {
        var enabled = selectedKind(form) === CUSTOM_VALUE;
        CUSTOM_FIELDS.forEach(function (name) {
            var input = named(form, name);
            if (!input) {
                return;
            }
            input.disabled = !enabled;
            var group = input.closest(".form-group");
            if (group) {
                group.style.display = enabled ? "" : "none";
            }
        });
    }

    function setValue(form, name, value) {
        var input = named(form, name);
        if (!input) {
            return;
        }
        if (input.type === "checkbox") {
            input.checked = value;
        } else {
            input.value = value;
        }
        input.dispatchEvent(new Event("change", {bubbles: true}));
    }

    document.addEventListener("change", function (event) {
        var form = event.target.form;
        if (form && event.target.matches('[name="list"], [name$="-list"]') &&
                named(form, "custom_columns")) {
            syncCustomFields(form);
        }
    });

    document.querySelectorAll('[name="custom_columns"], [name$="-custom_columns"]')
        .forEach(function (input) {
            syncCustomFields(input.form);
        });

    document.addEventListener("click", function (event) {
        var button = event.target.closest(".participantlist-adopt");
        if (!button) {
            return;
        }
        event.preventDefault();
        var form = button.closest("form");
        var message = form.querySelector(".participantlist-adopt-message");
        var pk = selectedKind(form);
        var kind = null;
        var kinds = form.querySelectorAll(".participantlist-kind");
        for (var i = 0; i < kinds.length; i++) {
            if (kinds[i].dataset.kind === pk) {
                kind = kinds[i];
            }
        }
        if (!kind) {
            message.textContent = button.dataset.hint;
            return;
        }
        message.textContent = "";
        setValue(form, "custom_name", kind.dataset.name);
        setValue(form, "custom_columns", kind.dataset.columns);
        setValue(form, "custom_sort", kind.dataset.sort);
        setValue(form, "custom_include_pending", kind.dataset.includePending === "1");
        selectCustom(form);
    });
}());
