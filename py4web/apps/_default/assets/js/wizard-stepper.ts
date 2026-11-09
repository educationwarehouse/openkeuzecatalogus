export {};

function center_active_wizard_step(): void {
    const $stepper_track = document.querySelector<HTMLElement>(".wizard-process-stepper-track");
    if (!$stepper_track || $stepper_track.scrollWidth <= $stepper_track.clientWidth) {
        return;
    }
    const $active_step =
        $stepper_track.querySelector<HTMLElement>(".steps .step.active") ||
        $stepper_track.querySelector<HTMLElement>(".steps .step.completed:last-child");
    if (!$active_step) {
        return;
    }
    const target_left = $active_step.offsetLeft - ($stepper_track.clientWidth - $active_step.clientWidth) / 2;
    $stepper_track.scrollTo({ left: Math.max(0, target_left), behavior: "auto" });
}

let active_signal: AbortSignal | null = null;

function initialize_wizard_stepper(): void {
    center_active_wizard_step();
    const { signal } = window.okl_page;
    if (active_signal !== signal) {
        active_signal = signal;
        window.addEventListener("resize", center_active_wizard_step, { signal });
    }
}

window.on_okl_ready(initialize_wizard_stepper);
document.addEventListener("htmx:afterSettle", () => {
    window.on_okl_ready(initialize_wizard_stepper);
});
