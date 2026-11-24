/*
 * Live updates for the attendee order list.
 *
 * Filter, search, sort arrows and pagination load only the result table
 * (see OrderListView.get_template_names) instead of the whole page.
 * Without JavaScript, all of them work as normal links and forms.
 */
$(function () {
    'use strict'

    const form = document.getElementById('participantlist-orders-filter')
    const results = document.getElementById('participantlist-orders-results')
    if (!form || !results || !window.fetch || !window.history.pushState) {
        return
    }
    const SEARCH_DELAY_MS = 300
    let controller = null
    let timer = null

    function filterUrl () {
        // A changed filter starts on page 1, so "page" is not taken over.
        const params = new URLSearchParams()
        for (const [key, value] of new FormData(form)) {
            if (value !== '') {
                params.append(key, value)
            }
        }
        const query = params.toString()
        return window.location.pathname + (query ? '?' + query : '')
    }

    function syncForm (url) {
        // Make the form match the loaded URL, e.g. after sorting or "back".
        const params = new URL(url, window.location.href).searchParams
        form.elements.status.value = params.get('status') || ''
        form.elements.query.value = params.get('query') || ''
        let ordering = form.elements.ordering
        if (!ordering) {
            ordering = document.createElement('input')
            ordering.type = 'hidden'
            ordering.name = 'ordering'
            form.prepend(ordering)
        }
        ordering.value = params.get('ordering') || ''
    }

    /**
     * Load the result table for ``url``.
     * ``mode`` is "push" (new history entry), "replace" or "none" (back/forward).
     */
    function load (url, mode) {
        if (controller) {
            controller.abort()
        }
        controller = new AbortController()
        results.setAttribute('aria-busy', 'true')
        results.style.opacity = '0.5'
        fetch(url, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            signal: controller.signal,
        }).then(function (response) {
            if (!response.ok || response.redirected) {
                // E.g. session expired: let the browser handle it.
                throw new Error('Unexpected response')
            }
            return response.text()
        }).then(function (html) {
            results.innerHTML = html
            // pretix' own initialisation (tooltips, ...).
            if (typeof setup_basics === 'function') {
                setup_basics($(results))
            }
            if (mode === 'push') {
                window.history.pushState(null, '', url)
            } else if (mode === 'replace') {
                window.history.replaceState(null, '', url)
            }
            syncForm(url)
            results.removeAttribute('aria-busy')
            results.style.opacity = ''
            if (results.getBoundingClientRect().top < 0) {
                results.scrollIntoView()
            }
        }).catch(function (error) {
            if (error.name !== 'AbortError') {
                window.location.href = url
            }
        })
    }

    form.elements.status.addEventListener('change', function () {
        load(filterUrl(), 'replace')
    })
    form.elements.query.addEventListener('input', function () {
        clearTimeout(timer)
        timer = setTimeout(function () {
            load(filterUrl(), 'replace')
        }, SEARCH_DELAY_MS)
    })
    form.addEventListener('submit', function (event) {
        event.preventDefault()
        clearTimeout(timer)
        load(filterUrl(), 'replace')
    })

    // Sort arrows, page links and page sizes: all are "?..." links in the results.
    // Capture phase, so pretix' own handler of the page selection does not run.
    results.addEventListener('click', function (event) {
        const link = event.target.closest('a')
        if (!link || !results.contains(link) || event.button !== 0 ||
            event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
            return
        }
        if (link.classList.contains('pagination-selection')) {
            // "Page x of y": ask for the page number, as pretix does.
            event.preventDefault()
            event.stopPropagation()
            const max = parseInt(link.dataset.max)
            const input = window.prompt(
                gettext('Enter page number between 1 and %(max)s.').replace('%(max)s', max)
            )
            if (input) {
                const page = parseInt(input)
                if (!page || page < 1 || page > max) {
                    window.alert(gettext('Invalid page number.'))
                } else {
                    load(window.location.pathname + link.dataset.href.replace('_PAGE_', page), 'push')
                }
            }
            return
        }
        const href = link.getAttribute('href')
        if (href && href.startsWith('?')) {
            event.preventDefault()
            load(window.location.pathname + href, 'push')
        }
    }, true)

    window.addEventListener('popstate', function () {
        load(window.location.href, 'none')
    })
})
