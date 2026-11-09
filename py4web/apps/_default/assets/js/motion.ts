export {};

declare global {
    interface Window {
        okl_page: AbortController;
        on_okl_ready: (callback: () => void) => void;
    }
}

const $initialized_motion = new WeakSet<HTMLElement>();

function initialize_landing_motion($landing: HTMLElement): void {
    const { signal } = window.okl_page;
    const reduced_motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const desktop_motion = window.matchMedia("(min-width: 992px)");
    const single_column_routes = window.matchMedia("(max-width: 767.98px)");
    const reveal_selector = '[data-motion="reveal"], [data-motion="photo-stack"], [data-motion-group]';
    const $observed = new Set<HTMLElement>();
    let motion_frame: number | undefined;

    function reveal($element: HTMLElement) {
        $element.classList.add("is-motion-visible");
        $observed.delete($element);
        if ($element.dataset.motion === "discussion-timeline") {
            reveal_initial_discussion_items();
        }
    }

    const reveal_observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) {
                    return;
                }
                const $element = entry.target as HTMLElement;
                reveal($element);
                reveal_observer.unobserve($element);
            });
        },
        {
            threshold: 0.15,
            rootMargin: "0px 0px -12% 0px",
        },
    );
    signal.addEventListener(
        "abort",
        () => {
            reveal_observer.disconnect();
            if (motion_frame !== undefined) {
                cancelAnimationFrame(motion_frame);
            }
        },
        { once: true },
    );

    function prepare_group_items($container: HTMLElement) {
        $container.querySelectorAll<HTMLElement>(":scope > .js-motion-item").forEach(($item, index) => {
            $item.style.setProperty("--motion-index", String(index));
        });
    }

    function prepare_reveal($element: HTMLElement) {
        if ($observed.has($element) || $element.classList.contains("is-motion-visible")) {
            return;
        }
        if ($element.hasAttribute("data-motion-group")) {
            prepare_group_items($element);
        }
        const rect = $element.getBoundingClientRect();
        const should_animate_immediately = $element.closest(".okl-hero") !== null;
        const is_below_initial_viewport = rect.top > window.innerHeight * 0.82;
        if (!should_animate_immediately && !is_below_initial_viewport) {
            reveal($element);
            return;
        }
        $element.classList.add("is-motion-pending");
        $observed.add($element);
        if (should_animate_immediately) {
            requestAnimationFrame(() => {
                return requestAnimationFrame(() => {
                    return reveal($element);
                });
            });
            return;
        }
        reveal_observer.observe($element);
    }

    function prepare_standard_reveals() {
        $landing.querySelectorAll<HTMLElement>(reveal_selector).forEach(prepare_reveal);
        if ($discussion) {
            prepare_reveal($discussion);
        }
        const $hero_art = $landing.querySelector<HTMLElement>('[data-motion="hero-art"]');
        if ($hero_art) {
            $hero_art.classList.add("is-motion-pending");
            requestAnimationFrame(() => {
                return requestAnimationFrame(() => {
                    return $hero_art.classList.add("is-motion-visible");
                });
            });
        }
    }

    function set_available($button: HTMLButtonElement, available: boolean) {
        $button.classList.toggle("is-unavailable", !available);
        $button.disabled = !available;
    }

    function initialise_theme_rail() {
        const $section = $landing.querySelector<HTMLElement>(".okl-themes");
        const $rail = $landing.querySelector<HTMLElement>("#okl-theme-rail");
        if (!$section || !$rail) {
            return;
        }
        const $dots_container = $section.querySelector<HTMLElement>(".okl-slider-dots");
        const $previous = $section.querySelector<HTMLButtonElement>(".okl-rail-btn--prev");
        const $next = $section.querySelector<HTMLButtonElement>(".okl-rail-btn--next");
        const $cards = [...$rail.querySelectorAll<HTMLElement>(".okl-theme-card")];
        if (!$dots_container || !$previous || !$next || !$cards.length) {
            return;
        }
        const $theme_section = $section;
        const $theme_rail = $rail;
        const $theme_dots = $dots_container;
        const $theme_previous = $previous;
        const $theme_next = $next;
        const epsilon = 2;
        let has_interacted = false;
        let rail_frame: number | undefined;
        let scroll_stops: number[] = [];
        let $dots: HTMLButtonElement[] = [];
        let rail_width = $theme_rail.clientWidth;

        function nearest_stop_index() {
            return scroll_stops.reduce((nearest, stop, index) => {
                return Math.abs(stop - $theme_rail.scrollLeft) <
                    Math.abs(scroll_stops[nearest] - $theme_rail.scrollLeft)
                    ? index
                    : nearest;
            }, 0);
        }

        function move_to(index: number) {
            const target = scroll_stops[Math.max(0, Math.min(index, scroll_stops.length - 1))];
            if (target === undefined) {
                return;
            }
            has_interacted = true;
            $theme_rail.scrollTo({
                left: target,
                behavior: reduced_motion.matches ? "auto" : "smooth",
            });
        }

        function build_dots() {
            const active_dot = nearest_stop_index();
            $theme_dots.replaceChildren();
            $dots = scroll_stops.map((_stop, index) => {
                const $dot = document.createElement("button");
                const is_active = index === active_dot;
                $dot.type = "button";
                $dot.className = `okl-slider-dot${is_active ? " is-active" : ""}`;
                $dot.setAttribute("aria-label", `Ga naar carrouselpositie ${index + 1} van ${scroll_stops.length}`);
                $dot.setAttribute("aria-current", is_active ? "true" : "false");
                $dot.addEventListener("click", () => {
                    return move_to(index);
                });
                $theme_dots.append($dot);
                return $dot;
            });
        }

        function calculate_stops() {
            const maximum = Math.max(0, $theme_rail.scrollWidth - $theme_rail.clientWidth);
            const first_card_offset = $cards[0]?.offsetLeft || 0;
            const candidates = $cards.map(($card) => {
                return Math.min(maximum, Math.max(0, $card.offsetLeft - first_card_offset));
            });
            const next_stops = candidates.filter((stop, index) => {
                return index === 0 || Math.abs(stop - candidates[index - 1]) > epsilon;
            });
            if (!next_stops.length) {
                next_stops.push(0);
            }
            const stops_changed =
                next_stops.length !== scroll_stops.length ||
                next_stops.some((stop, index) => {
                    return Math.abs(stop - scroll_stops[index]) > epsilon;
                });
            if (!stops_changed) {
                return;
            }
            scroll_stops = next_stops;
            build_dots();
        }

        function update() {
            rail_frame = undefined;
            const maximum = Math.max(0, $theme_rail.scrollWidth - $theme_rail.clientWidth);
            const at_start = $theme_rail.scrollLeft <= epsilon;
            const at_end = $theme_rail.scrollLeft >= maximum - epsilon;
            const active_dot = nearest_stop_index();
            $dots.forEach(($dot, index) => {
                const is_active = index === active_dot;
                $dot.classList.toggle("is-active", is_active);
                $dot.setAttribute("aria-current", is_active ? "true" : "false");
            });
            set_available($theme_previous, !at_start);
            set_available($theme_next, !at_end);
            $theme_section.classList.toggle("is-initial", at_start && !has_interacted);
            $theme_section.classList.toggle("can-scroll-left", !at_start);
            $theme_section.classList.toggle("can-scroll-right", !at_end);
        }

        function queue_update() {
            if ($theme_rail.scrollLeft > epsilon) {
                has_interacted = true;
            }
            if (rail_frame === undefined) {
                rail_frame = requestAnimationFrame(update);
            }
        }

        $theme_previous.addEventListener("click", () => {
            return move_to(nearest_stop_index() - 1);
        });
        $theme_next.addEventListener("click", () => {
            return move_to(nearest_stop_index() + 1);
        });
        $theme_rail.addEventListener("scroll", queue_update, { passive: true });
        window.addEventListener(
            "resize",
            () => {
                const next_rail_width = $theme_rail.clientWidth;
                if (Math.abs(next_rail_width - rail_width) <= epsilon) {
                    return;
                }
                rail_width = next_rail_width;
                calculate_stops();
                queue_update();
            },
            { signal },
        );
        calculate_stops();
        update();
    }

    const $timeline = $landing.querySelector<HTMLElement>('[data-motion="timeline"]');
    const $timeline_rows = $timeline ? [...$timeline.querySelectorAll<HTMLElement>(".okl-timeline__row")] : [];
    $timeline_rows.forEach(($row, index) => {
        $row.style.setProperty("--motion-index", String(index));
        $row.classList.add("is-motion-pending");
        $observed.add($row);
        reveal_observer.observe($row);
    });
    // Keep in sync with $okl-discussion-dot (1.25rem) in _brand-components.scss.
    const discussion_dot_size_px = 20;
    const $discussion = $landing.querySelector<HTMLElement>('[data-motion="discussion-timeline"]');
    const $discussion_viewport = $discussion?.querySelector<HTMLElement>(".okl-discussion__viewport");

    function scroll_rail_to(left: number) {
        if (!$discussion_viewport) {
            return;
        }
        $discussion_viewport.scrollLeft = left;
    }

    // The timeline itself enters as one calm section. Once it is present, the
    // existing horizontal-pan sweep remains: only contributions newly reached by
    // the reader animate, so the motion follows an intentional gesture instead
    // of competing with the section reveal.
    const motion_tokens = getComputedStyle(document.documentElement);
    const discussion_sweep_ms = parseFloat(motion_tokens.getPropertyValue("--okl-motion-timeline-sweep"));
    const discussion_step_ceiling_ms = parseFloat(motion_tokens.getPropertyValue("--okl-motion-timeline-stagger"));
    let last_discussion_scroll_left = $discussion_viewport?.scrollLeft ?? 0;
    let $pending_discussion_items: HTMLElement[] = [];

    function collect_discussion_items() {
        if (!$discussion) {
            return;
        }
        const selector = $discussion.classList.contains("is-full")
            ? ".okl-discussion__event-group"
            : ".okl-discussion__compact-column";
        $pending_discussion_items = [...$discussion.querySelectorAll<HTMLElement>(selector)].filter(($item) => {
            return !$item.classList.contains("is-motion-visible");
        });
        last_discussion_scroll_left = $discussion_viewport?.scrollLeft ?? 0;
    }

    function reveal_discussion_items(animate: boolean) {
        if (!$discussion || !$discussion_viewport || !$pending_discussion_items.length) {
            return;
        }
        const scroll_left = $discussion_viewport.scrollLeft;
        const moving_back = scroll_left < last_discussion_scroll_left;
        last_discussion_scroll_left = scroll_left;
        const viewport_rect = $discussion_viewport.getBoundingClientRect();
        const $still_pending: HTMLElement[] = [];
        const arriving: {
            item: HTMLElement;
            left: number;
        }[] = [];
        $pending_discussion_items.forEach(($item) => {
            const rect = $item.getBoundingClientRect();
            if (rect.right < viewport_rect.left || rect.left > viewport_rect.right) {
                $still_pending.push($item);
                return;
            }
            arriving.push({ item: $item, left: rect.left });
        });
        $pending_discussion_items = $still_pending;
        if (!arriving.length) {
            return;
        }
        arriving.sort((a, b) => {
            return moving_back ? b.left - a.left : a.left - b.left;
        });
        const step = animate ? Math.min(discussion_step_ceiling_ms, discussion_sweep_ms / arriving.length) : 0;
        arriving.forEach(({ item: $item }, index) => {
            $item.style.setProperty("--motion-delay", `${Math.round(index * step)}ms`);
            $item.classList.add("is-motion-visible");
        });
    }

    function reveal_initial_discussion_items() {
        if (!$discussion || !$discussion_viewport) {
            return;
        }
        reveal_discussion_items(false);
        update_year_progress();
        $discussion.classList.add("is-scroll-reveal-ready");
    }

    function build_discussion_overview() {
        const $empty = {
            line: undefined as HTMLElement | undefined,
            dots: new Map<string, HTMLElement>(),
            full_year_anchors: [] as HTMLElement[],
        };
        if (!$discussion || !$discussion_viewport) {
            return $empty;
        }
        const $sticky = $discussion.querySelector<HTMLElement>(".okl-discussion__full-axis-sticky");
        const $scroller = $sticky?.querySelector<HTMLElement>(".okl-discussion__full-axis-scroller");
        const $years = $scroller?.querySelector<HTMLElement>(".okl-discussion__full-years");
        const $full = $discussion.querySelector<HTMLElement>(".okl-discussion__full");
        const $event_groups = $full?.querySelector<HTMLElement>(".okl-discussion__event-groups");
        if (!$sticky || !$scroller || !$years || !$full || !$event_groups) {
            return $empty;
        }
        $discussion.insertBefore($sticky, $discussion_viewport);
        $full.insertBefore($years, $event_groups);
        // Kept, not just read for their `data-year` values: these are the
        // real, pixel-accurate anchors sitting above the card grid, one per
        // year, however wide that year's own column of cards is — see
        // `year_progress_fraction`, which reads their actual positions rather
        // than assuming every year takes an equal share of the scrollable
        // width the way the compressed overview below does.
        const $full_year_anchors = [...$years.querySelectorAll<HTMLElement>("[data-year]")];
        const year_values = $full_year_anchors
            .map(($anchor) => {
                return $anchor.dataset.year;
            })
            .filter((year): year is string => {
                return Boolean(year);
            });
        if (!year_values.length) {
            return $empty;
        }
        const $labels = document.createElement("div");
        $labels.className = "okl-discussion__overview-years";
        $labels.setAttribute("aria-hidden", "true");
        const $line = document.createElement("div");
        $line.className = "okl-discussion__full-line";
        $line.setAttribute("role", "group");
        $line.setAttribute("aria-label", "Spring naar een jaar in de tijdlijn");
        const $dots = new Map<string, HTMLElement>();
        const last = Math.max(1, year_values.length - 1);
        year_values.forEach((year, index) => {
            const at = `${(index / last) * 100}%`;
            const $label = document.createElement("span");
            $label.textContent = year;
            $label.style.left = at;
            $labels.append($label);
            // A real button, not the (inert, `aria-hidden`) label above: one
            // focusable, clickable control per year is enough — doubling it
            // onto the label too would just double the tab stops for the
            // same jump.
            const $dot = document.createElement("button");
            $dot.type = "button";
            $dot.dataset.year = year;
            $dot.style.left = at;
            $dot.setAttribute("aria-label", `Ga naar ${year}`);
            $line.append($dot);
            $dots.set(year, $dot);
        });
        $scroller.replaceChildren($labels, $line);
        $sticky.classList.add("is-ready");
        return { line: $line, dots: $dots, full_year_anchors: $full_year_anchors };
    }

    const {
        line: $discussion_full_line,
        dots: $discussion_full_line_dots,
        full_year_anchors: $discussion_full_year_anchors,
    } = build_discussion_overview();
    // Compact's own per-year segment (see tools/build_timeline.py) is the
    // real, pixel-accurate anchor there, the same role `discussionFullYearAnchors`
    // plays for the full view — read by `update_year_progress` below to work
    // out which of the two is actually current.
    const $discussion_compact_year_anchors = $discussion
        ? [...$discussion.querySelectorAll<HTMLElement>(".okl-discussion__compact-year.js-year-anchor")]
        : [];

    function year_anchor_centers($anchors: HTMLElement[]) {
        return $anchors.map(($anchor) => {
            return $anchor.getBoundingClientRect().left;
        });
    }

    function scroll_to_discussion_year(year: string) {
        if (!$discussion_viewport) {
            return;
        }
        const $anchors = $discussion?.classList.contains("is-full")
            ? $discussion_full_year_anchors
            : $discussion_compact_year_anchors;
        const $anchor = $anchors.find(($candidate) => {
            return $candidate.dataset.year === year;
        });
        if (!$anchor) {
            return;
        }
        const viewport_center =
            $discussion_viewport.getBoundingClientRect().left + $discussion_viewport.clientWidth / 2;
        $discussion_viewport.scrollBy({
            left: $anchor.getBoundingClientRect().left - viewport_center,
            behavior: reduced_motion.matches ? "auto" : "smooth",
        });
    }

    $discussion_full_line_dots.forEach(($dot, year) => {
        $dot.addEventListener("click", () => {
            return scroll_to_discussion_year(year);
        });
    });

    function year_progress_fraction(centers: number[], viewport_center: number) {
        if (centers.length < 2) {
            return centers.length ? 1 : 0;
        }
        const last = centers.length - 1;
        const next_index = centers.findIndex((center) => {
            return center >= viewport_center;
        });
        if (next_index === -1) {
            return 1;
        }
        if (next_index === 0) {
            return 0;
        }
        const span = centers[next_index] - centers[next_index - 1];
        const within = span > 0 ? (viewport_center - centers[next_index - 1]) / span : 0;
        return (next_index - 1 + Math.max(0, Math.min(1, within))) / last;
    }

    function update_year_progress() {
        if (!$discussion_viewport || !$discussion_full_line) {
            return;
        }
        const anchors = $discussion?.classList.contains("is-full")
            ? $discussion_full_year_anchors
            : $discussion_compact_year_anchors;
        if (!anchors.length) {
            return;
        }
        // When the content already fits, nothing is scrolled and there is no
        // "current position" for a centre to mean anything about — treat
        // that as fully reached rather than run the centre math, which would
        // otherwise mark only the years up to the (arbitrary, static)
        // viewport centre as reached even though every one of them is
        // already fully in view.
        const fits_without_scrolling = $discussion_viewport.scrollWidth <= $discussion_viewport.clientWidth;
        const viewport_center =
            $discussion_viewport.getBoundingClientRect().left + $discussion_viewport.clientWidth / 2;
        const fraction = fits_without_scrolling
            ? 1
            : year_progress_fraction(year_anchor_centers(anchors), viewport_center);
        $discussion_full_line.style.setProperty("--discussion-progress-fraction", String(fraction));
        // A dot's own fill wipes in, left to right, over the span the reader
        // is actually crossing — not a flat colour swap the instant its
        // threshold is reached — so the line visually flows into and through
        // the ring rather than handing off to it. Worked out from each dot's
        // own `left` percentage rather than measured with
        // `getBoundingClientRect`: the `<span>` itself carries no width or
        // height of its own — only its `::before`/`::after` do — so its rect
        // measures 0×0.
        const line_width = $discussion_full_line.getBoundingClientRect().width;
        const progress_px = fraction * line_width;
        const $dot_entries = [...$discussion_full_line_dots.values()];
        const last_dot_index = $dot_entries.length - 1;
        $dot_entries.forEach(($dot, index) => {
            // Mirrors the three `transform` cases in the CSS: a middle dot is
            // centred on its `left`, the first sits flush against it (no
            // shift) and the last sits flush against its own right edge.
            let dot_left_px: number;
            if (index === 0) {
                dot_left_px = 0;
            } else if (index === last_dot_index) {
                dot_left_px = line_width - discussion_dot_size_px;
            } else {
                dot_left_px = (parseFloat($dot.style.left) / 100) * line_width - discussion_dot_size_px / 2;
            }
            const raw = (progress_px - dot_left_px) / discussion_dot_size_px;
            const clamped = Math.max(0, Math.min(1, raw));
            $dot.style.setProperty("--okl-dot-fill", `${clamped * 100}%`);
            $dot.classList.toggle("is-year-active", clamped >= 1);
        });
    }

    function initialise_marker_preview(open_dialog?: (entry: string) => boolean) {
        if (!$discussion) {
            return;
        }
        const $preview = $discussion.querySelector<HTMLElement>(".js-okl-marker-preview");
        const $title = $preview?.querySelector("strong");
        const $meta = $preview?.querySelector("span");
        if (!$preview || !$title || !$meta) {
            return;
        }
        const $marker_discussion = $discussion;
        const $marker_preview = $preview;
        const $marker_title = $title;
        const $marker_meta = $meta;

        function hide() {
            $marker_preview.classList.remove("is-visible");
        }

        function show($marker: HTMLElement) {
            $marker_title.textContent = $marker.dataset.title || "";
            $marker_meta.textContent = $marker.dataset.meta || "";
            const anchor = $marker_discussion.getBoundingClientRect();
            const rect = $marker.getBoundingClientRect();
            // Measure once the text is in place, then clamp so a marker near
            // either end of the rail keeps its preview fully on screen.
            $marker_preview.classList.add("is-visible");
            const width = $marker_preview.offsetWidth;
            const centred = rect.left - anchor.left + rect.width / 2 - width / 2;
            const maximum = anchor.width - width - 16;
            $marker_preview.style.left = `${Math.round(Math.max(16, Math.min(centred, maximum)))}px`;
            $marker_preview.style.top = `${Math.round(rect.bottom - anchor.top + 12)}px`;
        }

        function marker_from(target: EventTarget | null) {
            return (target as HTMLElement | null)?.closest<HTMLElement>(".okl-discussion__marker") ?? undefined;
        }

        // A tap opens the contribution outright, so previewing on touch would
        // only flash something on the way there.
        const hover_capable = window.matchMedia("(hover: hover)");
        $marker_discussion.addEventListener("pointerover", (event) => {
            if (!hover_capable.matches || (event as PointerEvent).pointerType === "touch") {
                return;
            }
            const $marker = marker_from(event.target);
            if ($marker) {
                show($marker);
            }
        });
        $marker_discussion.addEventListener("pointerout", (event) => {
            if (marker_from(event.target)) {
                hide();
            }
        });
        $marker_discussion.addEventListener("focusin", (event) => {
            const $marker = marker_from(event.target);
            if ($marker) {
                show($marker);
            }
        });
        $marker_discussion.addEventListener("focusout", (event) => {
            if (marker_from(event.target)) {
                hide();
            }
        });
        // The preview is anchored to a position in the rail, so any movement of
        // that rail invalidates it.
        $discussion_viewport?.addEventListener("scroll", hide, { passive: true });
        window.addEventListener("resize", hide, { passive: true, signal });
        if (!open_dialog) {
            return;
        }
        // A press that travelled was a pan of the rail, not a choice of card.
        // The browser suppresses the click after a long swipe but not after a
        // short one, which is exactly the drag most likely to end on a card.
        const drag_threshold = 8;
        let press_origin:
            | {
                  x: number;
                  y: number;
              }
            | undefined;
        $marker_discussion.addEventListener("pointerdown", (event) => {
            press_origin = { x: event.clientX, y: event.clientY };
        });
        $marker_discussion.addEventListener("click", (event) => {
            const $trigger = (event.target as HTMLElement | null)?.closest<HTMLElement>(
                ".okl-discussion__marker, .okl-discussion__event-card[data-entry]",
            );
            if (!$trigger) {
                hide();
                return;
            }
            // Let the browser handle the link when it was asked to: a modified
            // or middle click means "open the source somewhere else".
            const mouse = event as MouseEvent;
            if (mouse.metaKey || mouse.ctrlKey || mouse.shiftKey || mouse.altKey || mouse.button !== 0) {
                return;
            }
            const travelled =
                press_origin &&
                Math.hypot(mouse.clientX - press_origin.x, mouse.clientY - press_origin.y) > drag_threshold;
            press_origin = undefined;
            if (travelled) {
                event.preventDefault();
                return;
            }
            const entry = $trigger.dataset.entry;
            if (!entry) {
                return;
            }
            hide();
            if (open_dialog(entry)) {
                event.preventDefault();
            }
        });
    }

    // A modal dialog blocks pointer events on the page but not wheel or touch
    // scrolling behind it, so the page has to be pinned. Pinning with a fixed
    // body rather than `overflow: hidden` because iOS ignores the latter; the
    // offset keeps the page where it was and the padding absorbs the scrollbar
    // that disappears, so nothing shifts on open or close.
    let pinned_scroll_y = 0;

    function pin_page() {
        pinned_scroll_y = window.scrollY;
        const scrollbar = window.innerWidth - document.documentElement.clientWidth;
        document.body.style.position = "fixed";
        document.body.style.insetInline = "0";
        document.body.style.top = `${-pinned_scroll_y}px`;
        if (scrollbar > 0) {
            document.body.style.paddingRight = `${scrollbar}px`;
        }
    }

    function release_page() {
        if (!document.body.style.position) {
            return;
        }
        document.body.style.position = "";
        document.body.style.insetInline = "";
        document.body.style.top = "";
        document.body.style.paddingRight = "";
        // Unpinning leaves the document at zero, so this is a jump back rather
        // than a movement. It has to be explicitly instant: Bootstrap's reboot
        // sets `scroll-behavior: smooth`, which would otherwise animate the
        // whole way down the page in view of the visitor.
        window.scrollTo({ top: pinned_scroll_y, left: 0, behavior: "instant" });
    }

    function initialise_source_dialog() {
        if (!$discussion) {
            return;
        }
        const $dialog = $discussion.querySelector<HTMLDialogElement>(".js-okl-source-dialog");
        if (!$dialog || typeof $dialog.showModal !== "function") {
            return;
        }
        const $type_field = $dialog.querySelector<HTMLElement>('[data-field="type"]');
        const $title_field = $dialog.querySelector<HTMLElement>('[data-field="title"]');
        const $meta_field = $dialog.querySelector<HTMLElement>('[data-field="meta"]');
        const $body_field = $dialog.querySelector<HTMLElement>('[data-field="body"]');
        const $link_field = $dialog.querySelector<HTMLAnchorElement>('[data-field="link"]');
        const $card = $dialog.querySelector<HTMLElement>(".okl-source-dialog__card");
        if (!$type_field || !$title_field || !$meta_field || !$body_field || !$link_field || !$card) {
            return;
        }
        const $source_discussion = $discussion;
        const $source_dialog = $dialog;
        const $source_type = $type_field;
        const $source_title = $title_field;
        const $source_meta = $meta_field;
        const $source_body = $body_field;
        const $source_link = $link_field;
        const $source_card = $card;
        const type_names: Record<string, string> = {
            "blog": "Blog",
            "pers": "Persbericht",
            "rapport": "Rapport",
            "social media": "Social media",
        };
        let bodies: Record<string, string> | undefined;
        let bodies_request: Promise<void> | undefined;
        let shown_entry = "";
        // Fetched once, on first use. Until it lands the card's own summary is
        // already on screen, so there is nothing to wait for.
        function load_bodies() {
            bodies_request ??= fetch("/data/discussion-descriptions.json")
                .then((response) => {
                    return response.ok ? response.json() : {};
                })
                .then((data) => {
                    bodies = data as Record<string, string>;
                })
                .catch(() => {
                    bodies = {};
                });
            return bodies_request;
        }

        function apply_body(entry: string, fallback: string) {
            $source_body.textContent = bodies?.[entry] || fallback;
        }

        function open(entry: string) {
            const $source = $source_discussion.querySelector<HTMLElement>(
                `.okl-discussion__event-card[data-entry="${CSS.escape(entry)}"]`,
            );
            if (!$source) {
                return false;
            }
            const $link = $source.querySelector<HTMLAnchorElement>(".okl-discussion__event-link");
            const author = $source.querySelector(".okl-discussion__event-footer strong")?.textContent?.trim() || "";
            const date = $source.querySelector(".okl-discussion__event-footer span")?.textContent?.trim() || "";
            const summary = $source.querySelector("p")?.textContent?.trim() || "";
            const type = $link?.dataset.type || "blog";
            shown_entry = entry;
            $source_card.dataset.type = type;
            $source_type.textContent = type_names[type] || type;
            $source_title.textContent = $source.querySelector("h3")?.textContent?.trim() || "";
            $source_meta.textContent = [author, date].filter(Boolean).join(" · ");
            $source_link.href = $link?.href || "#";
            apply_body(entry, summary);
            pin_page();
            $source_dialog.showModal();
            $source_body.scrollTop = 0;
            void load_bodies().then(() => {
                if (shown_entry === entry && $source_dialog.open) {
                    apply_body(entry, summary);
                }
            });
            return true;
        }

        $source_dialog.addEventListener("click", (event) => {
            // A click landing on the dialog itself is a click on its backdrop.
            if (event.target === $source_dialog) {
                $source_dialog.close();
            }
        });
        // Escape closes without passing through any handler of ours, so the page
        // is released on the event the dialog fires however it was dismissed.
        $source_dialog.addEventListener("close", release_page);
        $source_dialog.querySelector(".js-okl-dialog-close")?.addEventListener("click", () => {
            return $source_dialog.close();
        });
        return open;
    }

    function initialise_exclusive_disclosures() {
        if (!$discussion || "name" in HTMLDetailsElement.prototype) {
            return;
        }
        const $disclosures = [...$discussion.querySelectorAll<HTMLDetailsElement>(".okl-discussion__event-rest")];
        $disclosures.forEach(($disclosure) => {
            $disclosure.addEventListener("toggle", () => {
                if (!$disclosure.open) {
                    return;
                }
                $disclosures.forEach(($other) => {
                    if ($other !== $disclosure) {
                        $other.open = false;
                    }
                });
            });
        });
    }

    function initialise_discussion() {
        if (!$discussion || !$discussion_viewport) {
            return;
        }
        const $active_discussion = $discussion;
        const $active_viewport = $discussion_viewport;
        const $mode_switch = $active_discussion.querySelector<HTMLInputElement>(
            '.okl-view-switch input[type="checkbox"]',
        );

        function preserve_scroll_position(show_full: boolean) {
            const previous_maximum = $active_viewport.scrollWidth - $active_viewport.clientWidth;
            // On a wide screen the compact rail fits, so there is no position to
            // carry over — the rail opens on 2003 by default, so an unscrolled
            // view is at its start, not its end.
            const progress = previous_maximum > 0 ? $active_viewport.scrollLeft / previous_maximum : 0;
            $active_discussion.classList.add("is-switching");
            $active_discussion.classList.toggle("is-full", show_full);
            // Compact and full render different items. Rebuild the pending set
            // after the mode class changes, otherwise the hidden full columns
            // never receive their visible state.
            collect_discussion_items();
            requestAnimationFrame(() => {
                const next_maximum = Math.max(0, $active_viewport.scrollWidth - $active_viewport.clientWidth);
                scroll_rail_to(progress * next_maximum);
                reveal_discussion_items(false);
                update_year_progress();
                window.setTimeout(() => {
                    return $active_discussion.classList.remove("is-switching");
                }, 420);
            });
        }

        $mode_switch?.addEventListener("change", () => {
            return preserve_scroll_position($mode_switch.checked);
        });
        $active_viewport.addEventListener(
            "scroll",
            () => {
                reveal_discussion_items(true);
                update_year_progress();
            },
            { passive: true },
        );
        collect_discussion_items();
    }

    const parallax_elements = [
        ...$landing.querySelectorAll<HTMLElement>("[data-motion-parallax], [data-motion-scale]"),
    ];
    const $route_cards = [...$landing.querySelectorAll<HTMLElement>(".okl-route-card")];

    function update_mobile_route_cards() {
        if (reduced_motion.matches || !single_column_routes.matches) {
            $route_cards.forEach(($card) => {
                return $card.classList.remove("is-scroll-active");
            });
            return;
        }
        const viewport_center = window.innerHeight * 0.55;
        const visible_cards = $route_cards
            .map(($card) => {
                return { card: $card, rect: $card.getBoundingClientRect() };
            })
            .filter(({ rect }) => {
                return rect.bottom > 0 && rect.top < window.innerHeight;
            });
        const $active_card = visible_cards.reduce<HTMLElement | undefined>(($nearest, candidate) => {
            if (!$nearest) {
                return candidate.card;
            }
            const nearest_rect = $nearest.getBoundingClientRect();
            const nearest_distance = Math.abs((nearest_rect.top + nearest_rect.bottom) / 2 - viewport_center);
            const candidate_distance = Math.abs((candidate.rect.top + candidate.rect.bottom) / 2 - viewport_center);
            return candidate_distance < nearest_distance ? candidate.card : $nearest;
        }, undefined);
        $route_cards.forEach(($card) => {
            return $card.classList.toggle("is-scroll-active", $card === $active_card);
        });
    }

    // Generic "one item at a time is highlighted" behaviour: whichever item sits
    // closest to the reading line of the viewport gets `is-active`. Declared in
    // the markup so a group opts in without needing its own code path.
    const $scroll_focus_groups = [...$landing.querySelectorAll<HTMLElement>("[data-okl-scroll-focus]")]
        .map(($group) => {
            return [...$group.querySelectorAll<HTMLElement>("[data-okl-scroll-focus-item]")];
        })
        .filter(($items) => {
            return $items.length > 0;
        });

    function update_scroll_focus() {
        const reading_line = window.innerHeight * 0.5;
        $scroll_focus_groups.forEach(($items) => {
            let $active: HTMLElement | undefined;
            let shortest_distance = Number.POSITIVE_INFINITY;
            $items.forEach(($item) => {
                const rect = $item.getBoundingClientRect();
                if (rect.bottom <= 0 || rect.top >= window.innerHeight) {
                    return;
                }
                const distance = Math.abs((rect.top + rect.bottom) / 2 - reading_line);
                if (distance >= shortest_distance) {
                    return;
                }
                shortest_distance = distance;
                $active = $item;
            });
            // Off-screen groups keep whichever item was highlighted last, so the
            // section never renders with every row in its plain state.
            if (!$active) {
                return;
            }
            $items.forEach(($item) => {
                return $item.classList.toggle("is-active", $item === $active);
            });
        });
    }

    function update_scroll_motion() {
        motion_frame = undefined;
        if (reduced_motion.matches) {
            parallax_elements.forEach((element) => {
                element.style.setProperty("--motion-parallax-y", "0px");
                element.style.setProperty("--motion-parallax-scale", "1");
            });
            update_mobile_route_cards();
            update_scroll_focus();
            return;
        }
        const container_rects = new Map<HTMLElement, DOMRect>();
        parallax_elements.forEach((element) => {
            const keep_mobile_hero_scale = element.dataset.motionScaleMode === "hero";
            if (!desktop_motion.matches) {
                element.style.setProperty("--motion-parallax-y", "0px");
                // The hero photo is clipped by its own static silhouette, so it
                // can keep a restrained depth cue on a phone. Other art keeps
                // its original size there: their layered decoration would drift
                // when only the image layer scales.
                if (!keep_mobile_hero_scale) {
                    element.style.setProperty("--motion-parallax-scale", "1");
                    return;
                }
            }
            const container = element.closest<HTMLElement>(
                '[data-motion="hero-art"], [data-motion="example-art"], [data-motion="photo-stack"]',
            );
            if (!container) {
                return;
            }
            const rect = container_rects.get(container) ?? container.getBoundingClientRect();
            container_rects.set(container, rect);
            if (rect.bottom < 0 || rect.top > window.innerHeight) {
                return;
            }
            const viewport_progress = (window.innerHeight - rect.top) / (window.innerHeight + rect.height) - 0.5;
            if (desktop_motion.matches && element.hasAttribute("data-motion-parallax")) {
                const range = Number(element.dataset.motionParallax || 0);
                const offset = Math.max(-Math.abs(range), Math.min(Math.abs(range), viewport_progress * range * 2));
                element.style.setProperty("--motion-parallax-y", `${offset.toFixed(2)}px`);
            }
            if (element.hasAttribute("data-motion-scale")) {
                const scale_range = desktop_motion.matches
                    ? Number(element.dataset.motionScale || 0)
                    : Math.min(Number(element.dataset.motionScale || 0), 0.06);
                const scale_progress =
                    element.dataset.motionScaleMode === "hero"
                        ? Math.max(0, Math.min(1, -rect.top / rect.height))
                        : Math.max(0, Math.min(1, viewport_progress + 0.5));
                element.style.setProperty("--motion-parallax-scale", (1 + scale_progress * scale_range).toFixed(4));
            }
        });
        update_mobile_route_cards();
        update_scroll_focus();
    }

    function schedule_motion_frame() {
        if (motion_frame === undefined) {
            motion_frame = requestAnimationFrame(update_scroll_motion);
        }
    }

    function set_reduced_motion(is_reduced: boolean) {
        $landing.classList.toggle("is-reduced-motion", is_reduced);
        if (is_reduced) {
            $observed.forEach(($element) => {
                reveal_observer.unobserve($element);
                reveal($element);
            });
            $landing.querySelectorAll<HTMLElement>(".js-motion-item, [data-motion]").forEach(reveal);
        }
        schedule_motion_frame();
    }

    function initialise_toggles() {
        $landing.addEventListener("click", (event) => {
            const $target = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-okl-toggle="pressed"]');
            if (!$target) {
                return;
            }
            $target.setAttribute("aria-pressed", $target.getAttribute("aria-pressed") === "true" ? "false" : "true");
        });
    }

    function initialise_delivery_route() {
        const $route = $landing.querySelector<HTMLElement>(".js-okl-delivery-route");
        if (!$route) {
            return;
        }
        const $steps = [...$route.querySelectorAll<HTMLElement>("[data-okl-route-step]")];
        const $results = [...$route.querySelectorAll<HTMLElement>("[data-okl-route-result]")];
        const $progress = [...$route.querySelectorAll<HTMLElement>(".js-okl-route-progress")];
        const $restart = $route.querySelector<HTMLButtonElement>(".js-okl-route-restart");

        function show_step(index: number) {
            $steps.forEach(($step, step_index) => {
                $step.hidden = step_index !== index;
            });
            $results.forEach(($result) => {
                $result.hidden = true;
            });
            $progress.forEach(($marker, marker_index) => {
                $marker.classList.toggle("is-active", marker_index === index);
                $marker.classList.toggle("is-complete", marker_index < index);
            });
            if ($restart) {
                $restart.hidden = index === 0;
            }
            $steps[index]?.focus({ preventScroll: true });
        }

        function show_result(result_id: string) {
            const $result = $results.find(($item) => {
                return $item.dataset.oklRouteResult === result_id;
            });
            if (!$result) {
                return;
            }
            $steps.forEach(($step) => {
                $step.hidden = true;
            });
            $results.forEach(($item) => {
                $item.hidden = $item !== $result;
            });
            $progress.forEach(($marker) => {
                $marker.classList.remove("is-active");
                $marker.classList.add("is-complete");
            });
            if ($restart) {
                $restart.hidden = false;
            }
            $result.focus({ preventScroll: true });
        }

        $route.addEventListener("click", (event) => {
            const $answer = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>("[data-okl-route-answer]");
            if ($answer) {
                const destination = $answer.dataset.oklRouteAnswer;
                if (!destination) {
                    return;
                }
                if (destination.startsWith("result-")) {
                    show_result(destination);
                } else {
                    show_step(Number(destination));
                }
                return;
            }
            if ((event.target as HTMLElement | null)?.closest(".js-okl-route-restart")) {
                show_step(0);
            }
        });
        [...$steps, ...$results].forEach(($panel) => {
            $panel.tabIndex = -1;
        });
    }

    $landing.classList.add("is-motion-ready");
    initialise_toggles();
    initialise_delivery_route();
    initialise_theme_rail();
    initialise_discussion();
    initialise_exclusive_disclosures();
    initialise_marker_preview(initialise_source_dialog());
    prepare_standard_reveals();
    set_reduced_motion(reduced_motion.matches);
    window.addEventListener("scroll", schedule_motion_frame, { passive: true, signal });
    window.addEventListener("resize", schedule_motion_frame, { passive: true, signal });
    document.addEventListener(
        "visibilitychange",
        () => {
            $landing.classList.toggle("is-page-hidden", document.hidden);
        },
        { signal },
    );
    reduced_motion.addEventListener(
        "change",
        (event) => {
            return set_reduced_motion(event.matches);
        },
        { signal },
    );
    schedule_motion_frame();
}

function animate_process_hero(): void {
    const $hero = document.querySelector<HTMLElement>("[data-okl-process-hero]");
    const $artwork = $hero?.querySelector<HTMLElement>(".okl-process-artwork");
    if (!$hero || !$artwork) {
        return;
    }
    const process = $hero.dataset.oklProcessHero;
    const progress = parseFloat(getComputedStyle($hero).getPropertyValue("--okl-process-progress")) || 0;
    let previous;
    try {
        previous = JSON.parse(sessionStorage.getItem("okl-process-hero") || "null");
        sessionStorage.setItem("okl-process-hero", JSON.stringify({ process, progress }));
    } catch {
        // The step position still works when browser storage is unavailable.
        return;
    }
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const $first_step = $hero.querySelector('.steps .step:nth-child(2)[aria-current="step"]');
    const $same_process = previous?.process === process || (previous?.process === "new" && $first_step);
    if (
        !$same_process ||
        !Number.isFinite(previous?.progress) ||
        previous.progress === progress ||
        preference.matches
    ) {
        return;
    }
    if (document.documentElement.dataset.oklNavigating === "true") {
        return;
    }
    const style = getComputedStyle($artwork);
    const x = parseFloat(style.getPropertyValue("--okl-process-travel-x"));
    const y = parseFloat(style.getPropertyValue("--okl-process-travel-y"));
    const animation = $artwork.animate(
        [
            { transform: `translate(${previous.progress * x}px, ${previous.progress * y}px)` },
            { transform: style.transform },
        ],
        {
            duration: parseFloat(style.getPropertyValue("--okl-motion-step")),
            easing: style.getPropertyValue("--okl-motion-expressive").trim(),
        },
    );
    preference.addEventListener(
        "change",
        () => {
            if (preference.matches) {
                animation.cancel();
            }
        },
        { once: true, signal: window.okl_page.signal },
    );
    window.okl_page.signal.addEventListener(
        "abort",
        () => {
            return animation.cancel();
        },
        { once: true },
    );
}

function initialize_motion(): void {
    const $landing = document.querySelector<HTMLElement>(".js-okl-landing");
    if ($landing && !$initialized_motion.has($landing)) {
        $initialized_motion.add($landing);
        initialize_landing_motion($landing);
    }
    const $main = document.querySelector<HTMLElement>("main.okl-app");
    if (!$main || $initialized_motion.has($main) || !("IntersectionObserver" in window)) {
        return;
    }
    const $motion_main = $main;
    $initialized_motion.add($motion_main);
    animate_process_hero();
    const { signal } = window.okl_page;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const $observed = new WeakSet<Element>();
    const $pending = new Set<HTMLElement>();
    const animations = new Map<HTMLElement, Animation>();
    const style = getComputedStyle(document.documentElement);
    const duration = parseFloat(style.getPropertyValue("--okl-motion-reveal"));
    const stagger = parseFloat(style.getPropertyValue("--okl-motion-stagger"));
    const distance = style.getPropertyValue("--okl-motion-distance").trim();
    const easing = style.getPropertyValue("--okl-motion-expressive").trim();
    const observer = new IntersectionObserver(
        (entries) => {
            entries
                .filter((entry) => {
                    return entry.isIntersecting;
                })
                .forEach((entry, index) => {
                    const $element = entry.target as HTMLElement;
                    if (!$pending.has($element)) {
                        return;
                    }
                    show($element);
                    if (preference.matches || $element.contains(document.activeElement)) {
                        return;
                    }
                    const animation = $element.animate(
                        [
                            { opacity: 0, translate: `0 ${distance}` },
                            { opacity: 1, translate: "0 0" },
                        ],
                        { duration, easing, delay: Math.min(index, 4) * stagger, fill: "backwards" },
                    );
                    animations.set($element, animation);
                    animation.finished
                        .finally(() => {
                            return animations.delete($element);
                        })
                        .catch(() => {});
                });
        },
        { threshold: 0 },
    );

    function show($element: HTMLElement): void {
        observer.unobserve($element);
        $pending.delete($element);
        $element.classList.remove("okl-reveal-pending");
    }

    function observe(): void {
        $motion_main
            .querySelectorAll<HTMLElement>(
                ".wizard-start-card, .okl-login-panel__inner, .okl-catalog-feature, .okl-detail-media, .okl-vision-section-heading, .okl-recommendations-heading, [data-motion=reveal]",
            )
            .forEach(($element) => {
                if ($observed.has($element) || $element.closest(".modal, dialog")) {
                    return;
                }
                $observed.add($element);
                // Content already in view must never fade out when its observer first fires.
                if (preference.matches || $element.getBoundingClientRect().top < innerHeight) {
                    return;
                }
                $element.classList.add("okl-reveal-pending");
                $pending.add($element);
                observer.observe($element);
            });
    }

    function cancel(): void {
        $pending.forEach(show);
        animations.forEach((animation) => {
            return animation.cancel();
        });
        animations.clear();
    }

    $motion_main.addEventListener(
        "focusin",
        (event) => {
            const target = event.target;
            if (!(target instanceof Element)) {
                return;
            }
            $pending.forEach(($element) => {
                if ($element.contains(target)) {
                    show($element);
                }
            });
            animations.forEach((animation, $element) => {
                if ($element.contains(target)) {
                    animation.cancel();
                }
            });
        },
        { signal },
    );
    preference.addEventListener(
        "change",
        () => {
            if (preference.matches) {
                cancel();
            }
        },
        { signal },
    );
    window.addEventListener("beforeprint", cancel, { signal });
    signal.addEventListener(
        "abort",
        () => {
            observer.disconnect();
            cancel();
        },
        { once: true },
    );
    document.addEventListener("htmx:afterSettle", observe, { signal });
    observe();
}

window.on_okl_ready(initialize_motion);
document.addEventListener("htmx:afterSettle", () => {
    return window.on_okl_ready(initialize_motion);
});
