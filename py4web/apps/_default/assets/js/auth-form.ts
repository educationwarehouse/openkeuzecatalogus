export {};

function initialize_auth_form(): void {
    const $page = document.querySelector<HTMLElement>(".okl-login-page");
    const $form = $page?.querySelector<HTMLFormElement>(".okl-auth-form form");
    if (!$page || !$form || $form.dataset.oklEnhanced) {
        return;
    }
    $form.dataset.oklEnhanced = "true";
    $form.querySelectorAll<HTMLElement>(".form-group").forEach(($group) => {
        const $label = $group.querySelector<HTMLLabelElement>("label");
        const $control = $group.querySelector<HTMLInputElement | HTMLSelectElement>(
            "input.form-control, select.form-control",
        );
        if (!$label || !$control) {
            return;
        }
        const required = $label.querySelector("span") !== null;
        const label_text = $label.textContent?.replace("*", "").trim() || "";
        const placeholder = `${label_text}${required ? " *" : ""}`;
        if ($control instanceof HTMLSelectElement) {
            const $empty_option = Array.from($control.options).find(($option) => {
                return $option.value === "";
            });
            if ($empty_option) {
                $empty_option.textContent = placeholder;
            }
        } else {
            $control.placeholder = placeholder;
        }
    });
    const $email = $form.querySelector<HTMLInputElement>('input[name="email"]');
    const $register = $form.querySelector<HTMLAnchorElement>('a[href*="register"]');
    const $reset = $form.querySelector<HTMLAnchorElement>('a[href*="request_reset_password"]');
    if ($email && $page.dataset.authLogin === "true") {
        $email.placeholder = "E-mailadres";
        $email.type = "email";
        $email.autocomplete = "username";
        const $label = $form.querySelector<HTMLLabelElement>(`label[for="${$email.id}"]`);
        if ($label) {
            $label.textContent = "E-mailadres";
        }
    }
    if ($register) {
        $register.textContent = "Meld je aan.";
    }
    if ($reset) {
        $reset.textContent = "Wachtwoord vergeten?";
    }
}

window.on_okl_ready(initialize_auth_form);
document.addEventListener("htmx:afterSettle", () => {
    return window.on_okl_ready(initialize_auth_form);
});
