// Enhances catalogue capsule select controls and keeps their rendered pills in sync with input state.

function pill(label: string, value: string) {
    const $pill = document.createElement('span')
    $pill.className = 'selected-pill'

    const $label = document.createElement('span')
    $label.className = 'selected-pill-label'
    $label.textContent = label

    const $remove = document.createElement('span')
    $remove.className = 'selected-pill-remove'
    $remove.dataset.value = value
    $remove.textContent = '×'

    $pill.append($label, $remove)
    return $pill
}

function init_multiselect_widget($container: HTMLElement) {
    if (!$container || $container.getAttribute('data-enhanced-capsule-select') === 'true') {
        return
    }

    const $button = $container.querySelector<HTMLElement>('.dropdown-toggle')
    const $menu = $container.querySelector<HTMLElement>('.dropdown-menu')
    const $selected_text = $container.querySelector<HTMLElement>('.selected-text')
    const $selected_count = $container.querySelector<HTMLElement>('.selected-count')
    const $close_btn = $container.querySelector<HTMLElement>('.close-dropdown-btn')
    const $search_input = $container.querySelector<HTMLInputElement>('.capsule-search-input')
    const dropdown_items = Array.from($container.querySelectorAll<HTMLElement>('.dropdown-item'))
    const placeholder = $container.dataset.placeholder || 'Alles'
    const is_multiple = $container.dataset.widget === 'multi-select'

    if (!$button || !$menu || !$selected_text) {
        return
    }

    $button.removeAttribute('data-bs-toggle')
    $button.removeAttribute('data-bs-auto-close')

    function selected_items() {
        return dropdown_items.filter(($item: HTMLElement) => {
            const $input = $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')
            return Boolean($input && $input.checked)
        })
    }

    function sync_item_state($item: HTMLElement) {
        const $input = $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')
        const selected = Boolean($input && $input.checked)
        $item.classList.toggle('selected', selected)
        $item.setAttribute('aria-selected', selected ? 'true' : 'false')
    }

    function update_display() {
        const items = selected_items()
        const labels = items.map(($item) => $item.querySelector<HTMLElement>('.item-label')?.textContent?.trim() || '')
        const values = items.map(($item) => $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')?.value || '')

        if ($selected_count) {
            $selected_count.textContent = `${values.length} geselecteerd`
        }

        if (!values.length) {
            $selected_text!.classList.add('is-placeholder')
            $selected_text!.textContent = placeholder
            return
        }

        $selected_text!.classList.remove('is-placeholder')
        $selected_text!.textContent = ''
        const $fragment = document.createDocumentFragment()
        labels.forEach((label, index) => {
            $fragment.appendChild(pill(label, values[index]))
        })
        $selected_text!.appendChild($fragment)
    }

    function filter_items(term: string) {
        const needle = term.trim().toLowerCase()
        dropdown_items.forEach(($item) => {
            const haystack = ($item.dataset.search || '').toLowerCase()
            $item.classList.toggle('d-none', Boolean(needle) && !haystack.includes(needle))
        })
    }

    function close_menu() {
        $menu!.classList.remove('show')
        $button!.setAttribute('aria-expanded', 'false')
        document.removeEventListener('click', handle_document_click, true)
    }

    function open_menu() {
        $menu!.classList.add('show')
        $button!.setAttribute('aria-expanded', 'true')
        document.addEventListener('click', handle_document_click, true)
        if ($search_input) {
            $search_input.value = ''
            filter_items('')
            window.setTimeout(() => $search_input.focus(), 0)
        }
    }

    function handle_document_click(evt: MouseEvent) {
        if (!(evt.target instanceof Node) || !$container.contains(evt.target)) {
            close_menu()
        }
    }

    $button!.addEventListener('click', (evt) => {
        evt.preventDefault()
        evt.stopPropagation()
        if ($menu!.classList.contains('show')) {
            close_menu()
        } else {
            open_menu()
        }
    })

    dropdown_items.forEach(($item) => {
        const $input = $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')
        if (!$input) {
            return
        }

        sync_item_state($item)
        $input.addEventListener('change', () => {
            if (!is_multiple) {
                dropdown_items.forEach(sync_item_state)
            }
            sync_item_state($item)
            update_display()
            if (!is_multiple) {
                close_menu()
            }
        })
    })

    $selected_text!.addEventListener('click', (evt) => {
        if (!(evt.target instanceof Element)) {
            return
        }

        const $remove = evt.target.closest<HTMLElement>('.selected-pill-remove')
        if (!$remove) {
            return
        }

        evt.preventDefault()
        evt.stopPropagation()

        const value = String($remove.dataset.value || '')
        const $input = $container.querySelector<HTMLInputElement>(`input[type="checkbox"][value="${CSS.escape(value)}"], input[type="radio"][value="${CSS.escape(value)}"]`)
        if ($input) {
            $input.checked = false
            $input.dispatchEvent(new Event('change', {bubbles: true}))
        }
    })

    if ($close_btn) {
        $close_btn.addEventListener('click', (evt) => {
            evt.preventDefault()
            close_menu()
        })
    }

    if ($search_input) {
        $search_input.addEventListener('input', (evt: Event) => {
            if (!(evt.target instanceof HTMLInputElement)) {
                return
            }

            filter_items(evt.target.value || '')
        })
    }

    const $form = $container.closest('form')
    if ($form) {
        $form.addEventListener('reset', () => {
            window.setTimeout(() => {
                dropdown_items.forEach(sync_item_state)
                filter_items('')
                update_display()
            }, 0)
        })
    }


    $container.setAttribute('data-enhanced-capsule-select', 'true')
    update_display()
}

function enhance_all_multiselect($root: HTMLElement) {
    const $scope = $root || document.body
    $scope.querySelectorAll<HTMLElement>('[data-widget="multi-select"], [data-widget="single-select"]').forEach(elt => init_multiselect_widget(elt))
}

export function refresh_multiselect_widget($container: HTMLElement) {
    const $selected_text = $container.querySelector<HTMLElement>('.selected-text')
    const $selected_count = $container.querySelector<HTMLElement>('.selected-count')
    const dropdown_items = Array.from($container.querySelectorAll<HTMLElement>('.dropdown-item'))
    const placeholder = $container.dataset.placeholder || 'Alles'

    if (!$selected_text) {
        return
    }

    const selected_items = dropdown_items.filter(($item) => {
        const $input = $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')
        const selected = Boolean($input && $input.checked)
        $item.classList.toggle('selected', selected)
        $item.setAttribute('aria-selected', selected ? 'true' : 'false')
        return selected
    })

    const labels = selected_items.map(($item) => $item.querySelector<HTMLElement>('.item-label')?.textContent?.trim() || '')
    const values = selected_items.map(($item) => $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')?.value || '')

    if ($selected_count) {
        $selected_count.textContent = `${values.length} geselecteerd`
    }

    if (!values.length) {
        $selected_text.classList.add('is-placeholder')
        $selected_text.textContent = placeholder
        return
    }

    $selected_text.classList.remove('is-placeholder')
    $selected_text.textContent = ''
    const $fragment = document.createDocumentFragment()

    labels.forEach((label, index) => {
        $fragment.appendChild(pill(label, values[index]))
    })

    $selected_text.appendChild($fragment)
}

document.addEventListener('DOMContentLoaded', () => {
    enhance_all_multiselect(document.body)
})

document.addEventListener('htmx:afterSwap', (evt) => {
    if (evt.target instanceof HTMLElement) {
        enhance_all_multiselect(evt.target)
    }
})
