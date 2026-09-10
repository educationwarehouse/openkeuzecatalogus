type ComparisonKind = 'methode' | 'product'
type ComparisonItem = { gid: string, name: string }

function storage_key(kind: ComparisonKind) {
    return `catalogue-comparison:${kind}`
}

function selected_items(kind: ComparisonKind): ComparisonItem[] {
    try {
        const stored = JSON.parse(window.sessionStorage.getItem(storage_key(kind)) || '[]')
        if (!Array.isArray(stored)) {
            return []
        }

        const items = stored.flatMap((item): ComparisonItem[] => {
            if (typeof item === 'string' && item.length > 0) {
                return [{gid: item, name: item}]
            }

            if (
                typeof item === 'object'
                && item !== null
                && typeof item.gid === 'string'
                && item.gid.length > 0
                && typeof item.name === 'string'
            ) {
                return [{gid: item.gid, name: item.name}]
            }

            return []
        })

        return items.filter((item, index) => items.findIndex(({gid}) => gid === item.gid) === index)
    } catch {
        return []
    }
}

function save_selected_items(kind: ComparisonKind, items: ComparisonItem[]) {
    window.sessionStorage.setItem(storage_key(kind), JSON.stringify(items))
}

function comparison_kind(value: string | undefined): ComparisonKind | null {
    return value === 'methode' || value === 'product' ? value : null
}

function comparison_url(kind: ComparisonKind, items: ComparisonItem[]) {
    return `/compare/${kind}/${items.map(({gid}) => encodeURIComponent(gid)).join('/')}`
}

function refresh_comparison_selection($scope: ParentNode = document) {
    $scope.querySelectorAll<HTMLInputElement>('.comparison-selection').forEach(($input) => {
        const kind = comparison_kind($input.dataset.comparisonKind)
        const gid = $input.dataset.comparisonGid

        if (kind && gid) {
            $input.checked = selected_items(kind).some((item) => item.gid === gid)
        }
    })

    $scope.querySelectorAll<HTMLElement>('.comparison-tray').forEach(($launcher) => {
        const kind = comparison_kind($launcher.dataset.comparisonKind)
        if (!kind) {
            return
        }

        const items = selected_items(kind)
        const enabled = items.length >= 2
        const $link = $launcher.querySelector<HTMLAnchorElement>('.comparison-link')
        const $count = $launcher.querySelector<HTMLElement>('.comparison-count')
        const $items = $launcher.querySelector<HTMLUListElement>('.comparison-items')

        if ($count) {
            $count.textContent = String(items.length)
        }

        $launcher.hidden = items.length === 0

        if ($items) {
            $items.replaceChildren(...items.map((item) => comparison_item_element(kind, item)))
        }

        if ($link) {
            $link.href = enabled ? comparison_url(kind, items) : ''
            $link.classList.toggle('disabled', !enabled)
            $link.setAttribute('aria-disabled', String(!enabled))
        }
    })
}

function comparison_item_element(kind: ComparisonKind, item: ComparisonItem) {
    const $item = document.createElement('li')
    $item.className = 'comparison-item'

    const $name = document.createElement('span')
    $name.className = 'text-truncate'
    $name.textContent = item.name
    $item.append($name)

    const $remove = document.createElement('button')
    $remove.type = 'button'
    $remove.className = 'btn-close comparison-remove'
    $remove.dataset.comparisonGid = item.gid
    $remove.dataset.comparisonKind = kind
    $remove.setAttribute('aria-label', `${item.name} uit vergelijking verwijderen`)
    $item.append($remove)

    return $item
}

document.addEventListener('DOMContentLoaded', () => {
    refresh_comparison_selection()
})

document.addEventListener('htmx:afterSwap', (event) => {
    const target = (event as CustomEvent<{ target?: EventTarget }>).detail?.target
    if (target instanceof HTMLElement) {
        refresh_comparison_selection(target)
    }
})

document.addEventListener('change', (event) => {
    const $input = event.target
    if ($input instanceof HTMLInputElement && $input.matches('.comparison-differences-toggle')) {
        $input.closest<HTMLElement>('.comparison-page')?.classList.toggle('only-differences', $input.checked)
        return
    }

    if (!($input instanceof HTMLInputElement) || !$input.matches('.comparison-selection')) {
        return
    }

    const kind = comparison_kind($input.dataset.comparisonKind)
    const gid = $input.dataset.comparisonGid
    const name = $input.dataset.comparisonName
    if (!kind || !gid || !name) {
        return
    }

    const items = selected_items(kind)
    save_selected_items(
        kind,
        $input.checked
            ? [...items.filter((item) => item.gid !== gid), {gid, name}]
            : items.filter((item) => item.gid !== gid),
    )
    refresh_comparison_selection()
})

document.addEventListener('click', (event) => {
    const $target = event.target as Element | null;
    if (!$target) {
        return
    }

    const $remove = $target.closest<HTMLButtonElement>('.comparison-remove')
    if ($remove) {
        const kind = comparison_kind($remove.dataset.comparisonKind)
        const gid = $remove.dataset.comparisonGid
        if (kind && gid) {
            save_selected_items(kind, selected_items(kind).filter((item) => item.gid !== gid))
            refresh_comparison_selection()
            return
        }

    }


    const $link = $target.closest<HTMLAnchorElement>('.comparison-link')
    if ($link?.getAttribute('aria-disabled') === 'true') {
        event.preventDefault()
    }
})
