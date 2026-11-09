export {};

// Native date inputs follow the browser's locale (mm/dd/yyyy in an English browser),
// which no attribute can override. Flatpickr shows dd-mm-yyyy in a visible copy of the
// input while the original keeps submitting the ISO value py4web's validators expect.

interface FlatpickrInstance {
    altInput?: HTMLInputElement;
    destroy(): void;
}

interface FlatpickrOptions {
    locale: string;
    altInput: boolean;
    altInputClass: string;
    altFormat: string;
    dateFormat: string;
    enableTime: boolean;
    time_24hr: boolean;
    allowInput: boolean;
    clickOpens: boolean;
    disableMobile: boolean;
}

declare const flatpickr: (element: HTMLInputElement, options: FlatpickrOptions) => FlatpickrInstance;

const $enhanced_inputs = new WeakSet<HTMLInputElement>();

function enhance_date_input($input: HTMLInputElement): void {
    if ($enhanced_inputs.has($input)) {
        return;
    }
    $enhanced_inputs.add($input);
    const with_time = $input.type === "datetime-local";
    const $label = $input.labels?.[0];
    const name = $input.getAttribute("aria-label") || $label?.textContent?.trim() || $input.name;
    const instance = flatpickr($input, {
        locale: "nl",
        altInput: true,
        // flatpickr appends its own Bulma-style classes otherwise
        altInputClass: $input.className,
        altFormat: with_time ? "d-m-Y H:i" : "d-m-Y",
        dateFormat: with_time ? "Y-m-d\\TH:i" : "Y-m-d",
        enableTime: with_time,
        time_24hr: true,
        allowInput: !$input.readOnly,
        clickOpens: !$input.readOnly,
        // the mobile fallback is a native input again, with the locale format this replaces
        disableMobile: true,
    });
    const $alt_input = instance.altInput;
    if ($alt_input) {
        // the label still points at the original, which is now a hidden input
        $alt_input.setAttribute("aria-label", name);
        $alt_input.readOnly = $input.readOnly;
        $alt_input.placeholder = with_time ? "dd-mm-jjjj uu:mm" : "dd-mm-jjjj";
    }
    window.okl_page.signal.addEventListener(
        "abort",
        () => {
            return instance.destroy();
        },
        { once: true },
    );
}

function enhance_date_inputs(): void {
    document
        .querySelectorAll<HTMLInputElement>('input[type="date"], input[type="datetime-local"]')
        .forEach(enhance_date_input);
}

window.on_okl_ready(enhance_date_inputs);
document.addEventListener("htmx:afterSettle", enhance_date_inputs);
