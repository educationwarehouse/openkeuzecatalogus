// Keeps catalogue filter forms in sync with the URL and refreshes capsule select widgets after state changes.

import {refresh_multiselect_widget} from './multiselectwidget'

declare const htmx: {
    trigger(target: Element, event_name: string): void
}

function url_settings() {
    return new URLSearchParams(window.location.search)
}

function update_url_params($form: HTMLFormElement) {
    const query = new URLSearchParams()
    const form_data = new FormData($form)

    form_data.forEach((value, key) => {
        if (typeof value !== 'string' || !value) {
            return
        }

        query.append(key, value)
    })

    const url = new URL(window.location.href)
    const query_string = query.toString()
    url.search = query_string ? `?${query_string}` : ''
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
}

function url_to_state($form: HTMLFormElement) {
    const settings = url_settings()

    Array.from($form.elements).forEach((control) => {
        if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement || control instanceof HTMLTextAreaElement)) {
            return
        }

        if (!control.name) {
            return
        }

        const values = settings.getAll(control.name)
        if (control instanceof HTMLInputElement) {
            const type = control.type.toLowerCase()

            if (type === 'checkbox' || type === 'radio') {
                control.checked = values.includes(control.value) || (control.value === '1' && values.length > 0)
                return
            }

            control.value = values[0] || ''
            return
        }

        if (control instanceof HTMLSelectElement && control.multiple) {
            Array.from(control.options).forEach((option) => {
                option.selected = values.includes(option.value)
            })
            return
        }

        if (control instanceof HTMLSelectElement && values.length === 0) {
            return
        }

        control.value = values[0] || ''
    })

    $form.querySelectorAll<HTMLElement>('[data-widget="multi-select"], [data-widget="single-select"]').forEach(($container) => {
        refresh_multiselect_widget($container)
    })
}

const form_submit_timeout_by_form = new WeakMap<HTMLFormElement, number>()

type SubmitReason =
    | { kind: 'field_change'; field: string } // -> set to 1 or keep depending on 'field'
    | { kind: 'reset' } // clean filters -> set page to 1
    | { kind: 'sync_from_url' } // -> keep page as-is in the data
    | null

function page_input($form: HTMLFormElement) {
    return $form.querySelector<HTMLInputElement>('input[name="page"]')
}

function view_input($form: HTMLFormElement) {
    return $form.querySelector<HTMLInputElement>('input[name="view"]')
}

function edwh_state($base: Element | null = null): HTMLFormElement | null {
    return ($base || document).querySelector<HTMLFormElement>('form.edwh-state')
}

function should_reset_page(reason: SubmitReason) {
    if (!reason) {
        return false
    }

    if (reason.kind === 'reset') {
        return true
    }

    return reason.kind === 'field_change' && reason.field !== 'page'
}

function set_page(
    $form: HTMLFormElement,
    page: number,
    {submit = false, scroll = false}: { submit?: boolean; scroll?: boolean } = {},
) {
    const $page_input = page_input($form)

    if (!$page_input) {
        return
    }

    const normalized_page = String(Math.max(1, Math.trunc(page)))
    const page_changed = $page_input.value !== normalized_page
    $page_input.value = normalized_page

    if (submit && page_changed) {
        queue_form_submit($form, {kind: 'field_change', field: 'page'})
    }
    if (scroll) {
        window.scrollTo({top: 0, behavior: 'smooth'})
    }
}

function queue_form_submit($form: HTMLFormElement, reason: SubmitReason = null, delay_ms: number = 0) {
    const existing_timeout = form_submit_timeout_by_form.get($form)
    if (existing_timeout) {
        window.clearTimeout(existing_timeout)
    }

    const timeout = window.setTimeout(() => {
        if (should_reset_page(reason)) {
            set_page($form, 1)
        }

        update_url_params($form)
        htmx.trigger(document.body, "ew:state_changed")
        form_submit_timeout_by_form.delete($form)
    }, delay_ms)

    form_submit_timeout_by_form.set($form, timeout)
}

function enhance_state_form($form: HTMLFormElement) {
    if ($form.getAttribute('data-catalog-filters-enhanced') === 'true') {
        return
    }

    $form.addEventListener('change', (event) => {
        const target = event.target
        if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement)) {
            return
        }

        if (!target.name) {
            return
        }

        if (target instanceof HTMLInputElement) {
            const type = target.type.toLowerCase()
            if (type === 'search' || type === 'text') {
                return
            }
        }

        queue_form_submit($form, {kind: 'field_change', field: target.name})
    })

    $form.addEventListener('input', (event) => {
        const target = event.target
        if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
            return
        }

        if (!target.name) {
            return
        }

        const type = target.type.toLowerCase()
        if (type !== 'search' && type !== 'text') {
            return
        }

        queue_form_submit($form, {kind: 'field_change', field: target.name}, 400)
    })

    $form.addEventListener('reset', () => {
        window.setTimeout(() => {
            $form.querySelectorAll<HTMLElement>('[data-widget="multi-select"], [data-widget="single-select"]').forEach(($container) => {
                refresh_multiselect_widget($container)
            })
            queue_form_submit($form, {kind: 'reset'})
        }, 0)
    })

    $form.setAttribute('data-catalog-filters-enhanced', 'true')
    url_to_state($form)
    queue_form_submit($form, {kind: 'sync_from_url'})
}

function enhance_state_forms($root: HTMLElement) {
    const $scope = $root || document.body

    const $form = edwh_state($scope);

    if ($form) {
        enhance_state_form($form)
    }

}

document.addEventListener('DOMContentLoaded', () => {
    enhance_state_forms(document.body)
})

document.addEventListener('htmx:afterSwap', (evt) => {
    if (evt.target) {
        enhance_state_forms(evt.target as HTMLElement)
    }
})

document.addEventListener('ew:change_page', (event: Event) => {
    const $form = edwh_state()

    if (!$form) {
        return
    }

    const page = Number((event as CustomEvent).detail?.page)

    if (!Number.isFinite(page)) {
        return
    }

    set_page($form, page, {scroll: true, submit: true})
})

document.addEventListener('ew:change_view', (event: Event) => {
    const $form = edwh_state()
    if (!$form) {
        return
    }

    const $view_input = view_input($form)
    if (!$view_input) {
        return
    }

    const view = String((event as CustomEvent).detail?.view || '').toLowerCase()

    if ($view_input.value === view) {
        // nothing changed
        return
    }

    $view_input.value = view
    set_page($form, 1, {submit: false})
    queue_form_submit($form, {kind: 'field_change', field: 'view'})
})

window.addEventListener('popstate', () => {
    const $form = edwh_state();

    if ($form) {
        url_to_state($form)
        queue_form_submit($form, {kind: 'sync_from_url'})
    }
})
