'use strict';

{
    const filter = document.getElementById('nav-filter');
    const sidebar = document.getElementById('nav-sidebar');
    if (filter && sidebar) {
        const items = Array.from(sidebar.querySelectorAll('[data-navigation-item]'));
        const groups = Array.from(sidebar.querySelectorAll('[data-navigation-group]'));
        const empty = sidebar.querySelector('[data-navigation-empty]');
        const status = document.getElementById('maru-navigation-search-status');
        const openBeforeSearch = new WeakMap();
        let filtering = false;

        function normalizeSearchText(value) {
            return value
                .normalize('NFKD')
                .replace(/[\u0300-\u036f]/g, '')
                .toLocaleLowerCase()
                .trim();
        }

        function collapsibleFor(group) {
            if (group.matches('details')) {
                return group;
            }
            return group.querySelector('[data-navigation-collapsible]');
        }

        function applyFilter(event) {
            if (event && event.key === 'Escape') {
                filter.value = '';
            }
            const query = normalizeSearchText(filter.value);
            const queryTerms = query.split(/\s+/).filter(Boolean);
            if (query && !filtering) {
                for (const group of groups) {
                    const collapsible = collapsibleFor(group);
                    if (collapsible) {
                        openBeforeSearch.set(collapsible, collapsible.open);
                    }
                }
            }
            let visibleCount = 0;
            for (const item of items) {
                const searchText = normalizeSearchText(
                    item.dataset.navigationSearch || item.textContent || ''
                );
                const matches = queryTerms.every((term) => searchText.includes(term));
                item.hidden = !matches;
                if (matches) {
                    visibleCount += 1;
                }
            }
            for (const group of groups) {
                const hasMatch = Boolean(
                    group.querySelector('[data-navigation-item]:not([hidden])')
                );
                const isSearchOnly = group.dataset.navigationSearchOnly === 'true';
                const isCurrent = group.dataset.navigationCurrent === 'true';
                group.hidden = !hasMatch || (!query && isSearchOnly && !isCurrent);
                const collapsible = collapsibleFor(group);
                if (collapsible && query) {
                    collapsible.open = hasMatch;
                } else if (collapsible && filtering && openBeforeSearch.has(collapsible)) {
                    collapsible.open = openBeforeSearch.get(collapsible);
                }
            }
            filtering = Boolean(query);
            if (empty) {
                empty.hidden = visibleCount !== 0;
            }
            filter.classList.toggle('no-results', visibleCount === 0);
            if (status) {
                status.textContent = query
                    ? `${visibleCount} available page${visibleCount === 1 ? '' : 's'} found.`
                    : `${items.length} available pages.`;
            }
            try {
                sessionStorage.setItem('django.admin.navSidebarFilterValue', query);
            } catch {
                // Navigation still works when browser storage is unavailable.
            }
        }

        filter.addEventListener('input', applyFilter);
        filter.addEventListener('keyup', applyFilter);
        let storedValue = '';
        try {
            storedValue = sessionStorage.getItem('django.admin.navSidebarFilterValue') || '';
        } catch {
            // An empty filter is a safe fallback when browser storage is unavailable.
        }
        if (storedValue) {
            filter.value = storedValue;
        }
        applyFilter();

        for (const gateway of document.querySelectorAll(
            '[data-navigation-specialist-gateway]'
        )) {
            gateway.addEventListener('click', (event) => {
                const specialistGroup = groups.find(
                    (group) => group.dataset.navigationGroup === 'specialist-records'
                );
                if (!specialistGroup) {
                    return;
                }
                event.preventDefault();
                filter.value = '';
                applyFilter();
                specialistGroup.hidden = false;
                const collapsible = collapsibleFor(specialistGroup);
                if (collapsible) {
                    collapsible.open = true;
                }
                specialistGroup.scrollIntoView({block: 'nearest'});
                filter.focus();
            });
        }
    }
}
