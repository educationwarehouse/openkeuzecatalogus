export {};

function initialize_faq_search(): void {
    const $input = document.querySelector<HTMLInputElement>("#faq-search");
    const $items = document.querySelectorAll<HTMLElement>(".js-faq-item");
    const $categories = document.querySelectorAll<HTMLElement>(".js-faq-category");
    const $empty = document.querySelector<HTMLElement>(".js-faq-empty");
    if (!$input || !$items.length || $input.dataset.oklEnhanced) {
        return;
    }
    $input.dataset.oklEnhanced = "true";
    $input.addEventListener(
        "input",
        () => {
            const term = $input.value.trim().toLocaleLowerCase();
            let any_visible = false;
            $categories.forEach(($category) => {
                let category_has_match = false;
                $category.querySelectorAll<HTMLElement>(".js-faq-item").forEach(($item) => {
                    const matches = !term || ($item.dataset.faqSearch || "").includes(term);
                    $item.classList.toggle("d-none", !matches);
                    category_has_match ||= matches;
                    any_visible ||= matches;
                });
                $category.classList.toggle("d-none", !category_has_match);
            });
            $empty?.classList.toggle("d-none", any_visible || !term);
        },
        { signal: window.okl_page.signal },
    );
}

window.on_okl_ready(initialize_faq_search);
document.addEventListener("htmx:afterSettle", () => {
    return window.on_okl_ready(initialize_faq_search);
});
