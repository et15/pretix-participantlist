/* Export page: copy a list kind into the "Custom list" fields. */
(function () {
    "use strict";

    var CUSTOM_VALUE = "__custom__";

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
