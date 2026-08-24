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
        const legacyFilterKey = 'django.admin.navSidebarFilterValue';
        let filtering = false;

        function clearLegacyFilterPersistence() {
            try {
                sessionStorage.removeItem(legacyFilterKey);
            } catch {
                // Navigation remains page-local when browser storage is unavailable.
            }
        }

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

        function applyFilter() {
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
            let taskCount = 0;
            let advancedCount = 0;
            for (const item of items) {
                const searchText = normalizeSearchText(
                    item.dataset.navigationSearch || item.textContent || ''
                );
                const matches = queryTerms.every((term) => searchText.includes(term));
                item.hidden = !matches;
                if (matches) {
                    if (item.dataset.navigationKind === 'specialist') {
                        advancedCount += 1;
                    } else {
                        taskCount += 1;
                    }
                }
            }
            for (const group of groups) {
                const hasMatch = Boolean(
                    group.querySelector('[data-navigation-item]:not([hidden])')
                );
                const isSearchOnly = group.dataset.navigationSearchOnly === 'true';
                const isCurrent = group.dataset.navigationCurrent === 'true';
                const isAdvanced = group.dataset.navigationGroupKind === 'advanced';
                group.hidden = !hasMatch || (!query && isSearchOnly && !isCurrent);
                const collapsible = collapsibleFor(group);
                if (collapsible && query) {
                    collapsible.open = Boolean(
                        hasMatch &&
                        (!isAdvanced || isCurrent || openBeforeSearch.get(collapsible))
                    );
                } else if (collapsible && filtering && openBeforeSearch.has(collapsible)) {
                    collapsible.open = openBeforeSearch.get(collapsible);
                }
            }
            filtering = Boolean(query);
            const visibleCount = taskCount + advancedCount;
            if (empty) {
                empty.hidden = visibleCount !== 0;
            }
            filter.classList.toggle('no-results', visibleCount === 0);
            if (status) {
                status.hidden = !query;
                status.textContent = query
                    ? [
                        `${taskCount} task${taskCount === 1 ? '' : 's'}`,
                        `${advancedCount} technical record${advancedCount === 1 ? '' : 's'} in Specialist records`,
                    ].join(' · ')
                    : '';
            }
            clearLegacyFilterPersistence();
        }

        filter.addEventListener('input', applyFilter);
        filter.addEventListener('change', applyFilter);
        filter.addEventListener('keyup', clearLegacyFilterPersistence);
        filter.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape' || !filter.value) {
                return;
            }
            event.preventDefault();
            filter.value = '';
            applyFilter();
        });
        filter.value = '';
        clearLegacyFilterPersistence();
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

{
    const focusTarget = document.querySelector('[data-maru-focus-on-load]');
    if (focusTarget instanceof HTMLElement) {
        requestAnimationFrame(() => focusTarget.focus());
    }
}
