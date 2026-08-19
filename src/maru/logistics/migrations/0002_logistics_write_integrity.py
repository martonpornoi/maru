"""Protect Logistics custody evidence and exact physical scope in PostgreSQL."""

# ruff: noqa: E501, PERF401

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

APPEND_ONLY_TABLES = (
    "logistics_equipmentofferitem",
    "logistics_equipmentofferhistory",
    "logistics_equipmentofferacceptance",
    "logistics_keyholderresponsibility",
    "logistics_assetagreement",
    "logistics_reusablekitline",
    "logistics_logisticsmanifestline",
    "logistics_logisticsevent",
    "logistics_offlinescanoperation",
    "logistics_offlineoperationreceipt",
    "logistics_logisticscommandreceipt",
)

ENTITY_TABLES = (
    "logistics_logisticsparty",
    "logistics_equipmentoffer",
    "logistics_logisticsnode",
    "logistics_asset",
    "logistics_stocklot",
    "logistics_physicalkey",
    "logistics_reusablekit",
    "logistics_logisticsmanifest",
    "logistics_logisticslabel",
    "logistics_logisticscurrentstate",
    "logistics_logisticsdiscrepancy",
    "logistics_logisticseditioncontrol",
    "logistics_offlinescanbatch",
)

TRUNCATE_TABLES = tuple(
    dict.fromkeys(
        (
            *APPEND_ONLY_TABLES,
            *ENTITY_TABLES,
            "logistics_restrictedlogisticsaddress",
        )
    )
)

CORE_FUNCTION_SQL = r"""
CREATE FUNCTION public.maru_prevent_logistics_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'TRUNCATE'
       AND public.maru_authority_provenance_test_reset_allowed()
    THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Logistics evidence is append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_logistics_entity_identity()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF TG_TABLE_NAME = 'logistics_logisticscurrentstate' THEN
            IF NEW.event_sequence <> 1 THEN
                RAISE EXCEPTION 'current Logistics projection must start at event one'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'logistics_logisticseditioncontrol' THEN
            IF NEW.aggregate_version <> 0 THEN
                RAISE EXCEPTION 'Logistics edition control starts at version zero'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            IF NEW.aggregate_version <> 1 THEN
                RAISE EXCEPTION 'Logistics aggregates start at version one'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF TG_TABLE_NAME IN (
            'logistics_logisticsparty',
            'logistics_logisticsnode',
            'logistics_asset',
            'logistics_stocklot',
            'logistics_physicalkey',
            'logistics_reusablekit',
            'logistics_logisticslabel'
        ) THEN
            IF (to_jsonb(NEW) ->> 'lifecycle') <> 'active' THEN
                RAISE EXCEPTION 'Logistics catalog records start active'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF TG_TABLE_NAME = 'logistics_equipmentoffer' THEN
            IF NEW.status <> 'pending'
               OR NEW.reviewed_by_id IS NOT NULL
               OR NEW.reviewed_at IS NOT NULL
               OR NEW.review_reason <> ''
               OR NEW.responsible_department_id IS NOT NULL
            THEN
                RAISE EXCEPTION 'equipment offers start pending and unreviewed'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF TG_TABLE_NAME = 'logistics_logisticsmanifest' THEN
            IF NEW.status <> 'draft' THEN
                RAISE EXCEPTION 'Logistics manifests start in draft'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF TG_TABLE_NAME = 'logistics_logisticsdiscrepancy' THEN
            IF NEW.status <> 'open'
               OR NEW.resolved_by_id IS NOT NULL
               OR NEW.resolved_at IS NOT NULL
               OR NEW.resolution_reason <> ''
            THEN
                RAISE EXCEPTION 'Logistics discrepancies start open and unresolved'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF TG_TABLE_NAME = 'logistics_offlinescanbatch' THEN
            IF NEW.status <> 'pending' THEN
                RAISE EXCEPTION 'offline Logistics batches start pending'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Logistics records require governed lifecycle changes'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
    THEN
        RAISE EXCEPTION 'Logistics identity and tenant scope are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME NOT IN (
        'logistics_equipmentoffer',
        'logistics_physicalkey',
        'logistics_logisticsmanifest',
        'logistics_logisticscurrentstate',
        'logistics_logisticseditioncontrol',
        'logistics_offlinescanbatch'
    ) THEN
        RAISE EXCEPTION 'this Logistics record has no governed update command'
            USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME <> 'logistics_logisticscurrentstate' THEN
        IF NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'Logistics aggregate versions advance exactly once'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'logistics_physicalkey' THEN
        IF NEW.label IS DISTINCT FROM OLD.label
           OR NEW.lifecycle IS DISTINCT FROM OLD.lifecycle
           OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
        THEN
            RAISE EXCEPTION 'physical-key updates only advance governed responsibility evidence'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'logistics_logisticsmanifest' THEN
        IF NEW.title IS DISTINCT FROM OLD.title
           OR NEW.loading_starts_at IS DISTINCT FROM OLD.loading_starts_at
           OR NEW.loading_ends_at IS DISTINCT FROM OLD.loading_ends_at
           OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
           OR (
                NEW.status IS NOT DISTINCT FROM OLD.status
                AND (
                    OLD.status <> 'draft'
                    OR NEW.line_count <> OLD.line_count + 1
                )
           )
           OR (
                NEW.status IS DISTINCT FROM OLD.status
                AND (
                    NEW.line_count <> OLD.line_count
                    OR (OLD.status, NEW.status) NOT IN (
                        ('draft', 'sealed'),
                        ('sealed', 'completed'),
                        ('draft', 'cancelled'),
                        ('sealed', 'cancelled')
                    )
                )
           )
        THEN
            RAISE EXCEPTION 'manifest updates must match a closed command transition'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.status = 'draft' AND NEW.status = 'sealed' THEN
            IF NOT EXISTS (
                SELECT 1
                  FROM public.logistics_logisticsmanifestline AS line
                 WHERE line.manifest_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'sealed manifest requires immutable line evidence'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.kind NOT IN ('inbound', 'stage_receiving') AND EXISTS (
                SELECT 1
                  FROM public.logistics_logisticsmanifestline AS line
                  LEFT JOIN public.logistics_logisticscurrentstate AS state
                    ON state.node_id IS NOT DISTINCT FROM line.node_id
                   AND state.asset_id IS NOT DISTINCT FROM line.asset_id
                   AND state.stock_lot_id IS NOT DISTINCT FROM line.stock_lot_id
                   AND state.physical_key_id IS NOT DISTINCT FROM line.physical_key_id
                 WHERE line.manifest_id = NEW.id
                   AND (
                        state.id IS NULL
                        OR (
                            line.stock_lot_id IS NOT NULL
                            AND line.quantity IS DISTINCT FROM state.quantity_on_hand
                        )
                        OR (
                            NEW.source_node_id IS NOT NULL
                            AND NOT EXISTS (
                                WITH RECURSIVE containing(node_id) AS (
                                    SELECT state.current_node_id
                                    UNION
                                    SELECT parent_state.current_node_id
                                      FROM public.logistics_logisticscurrentstate AS parent_state
                                      JOIN containing
                                        ON parent_state.node_id = containing.node_id
                                     WHERE parent_state.current_node_id IS NOT NULL
                                )
                                SELECT 1
                                  FROM containing
                                 WHERE node_id = NEW.source_node_id
                            )
                        )
                   )
            ) THEN
                RAISE EXCEPTION 'sealed manifest subjects must match source state and quantity'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_logistics_person_is_eligible(
    candidate_account_id uuid,
    acting_account_id uuid,
    scope_organization_id uuid,
    scope_edition_id uuid
)
RETURNS boolean AS $$
    SELECT EXISTS (
        SELECT 1
          FROM public.identity_account AS account
         WHERE account.id = candidate_account_id
           AND account.account_kind = 'person'
           AND account.is_active
           AND (
                account.id = acting_account_id
                OR EXISTS (
                    SELECT 1
                      FROM public.workforce_positionassignment AS assignment
                     WHERE assignment.account_id = account.id
                       AND assignment.organization_id = scope_organization_id
                       AND assignment.status = 'active'
                       AND (
                            scope_edition_id IS NULL
                            OR assignment.edition_id = scope_edition_id
                       )
                )
                OR EXISTS (
                    SELECT 1
                      FROM public.logistics_equipmentoffer AS offer
                     WHERE offer.offered_by_id = account.id
                       AND offer.organization_id = scope_organization_id
                       AND (
                            scope_edition_id IS NULL
                            OR offer.edition_id = scope_edition_id
                       )
                )
           )
    );
$$ LANGUAGE sql
STABLE
SET search_path = pg_catalog, public, pg_temp;
"""

ADDRESS_FUNCTION_SQL = r"""
CREATE FUNCTION public.maru_guard_logistics_restricted_address()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' AND (
        NEW.aggregate_version <> 1 OR NEW.lifecycle <> 'active'
    ) THEN
        RAISE EXCEPTION 'restricted Logistics contacts start active at version one'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'restricted Logistics contacts require governed disposal'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.purpose IS DISTINCT FROM OLD.purpose
           OR NEW.retention_until IS DISTINCT FROM OLD.retention_until
           OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
        THEN
            RAISE EXCEPTION 'restricted contact identity, purpose, and retention are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.lifecycle <> 'active'
           OR NEW.lifecycle <> 'disposed'
           OR NEW.aggregate_version <> OLD.aggregate_version + 1
           OR OLD.retention_until IS NULL
           OR OLD.retention_until >= clock_timestamp()
           OR NEW.subject_account_id IS NOT NULL
           OR NEW.party_id IS NOT NULL
           OR NEW.label <> 'Disposed'
           OR NEW.recipient_name <> ''
           OR NEW.contact_email <> ''
           OR NEW.contact_phone <> ''
           OR NEW.postal_address <> ''
           OR NEW.access_instructions <> ''
        THEN
            RAISE EXCEPTION 'restricted contact updates must be complete expired-data disposal'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM public.logistics_assetagreement AS agreement
             WHERE agreement.return_address_id = OLD.id
               AND agreement.return_due_at >= clock_timestamp()
        ) OR EXISTS (
            SELECT 1
             FROM public.logistics_equipmentoffer AS offer
             WHERE offer.pickup_address_id = OLD.id
               AND (
                    offer.available_until >= clock_timestamp()
                    OR offer.requested_return_at >= clock_timestamp()
               )
        ) OR EXISTS (
            SELECT 1
              FROM public.logistics_logisticsnode AS node
             WHERE node.storage_address_id = OLD.id
               AND node.lifecycle = 'active'
        ) THEN
            RAISE EXCEPTION 'restricted contact is still required by a live return horizon'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.edition_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
          FROM public.events_eventedition AS edition
         WHERE edition.id = NEW.edition_id
           AND edition.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'restricted contact edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.party_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
          FROM public.logistics_logisticsparty AS party
         WHERE party.id = NEW.party_id
           AND party.organization_id = NEW.organization_id
           AND party.lifecycle = 'active'
    ) THEN
        RAISE EXCEPTION 'restricted contact party scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.subject_account_id IS NOT NULL AND NEW.party_id IS NOT NULL THEN
        RAISE EXCEPTION 'restricted contact has more than one subject'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.subject_account_id IS NOT NULL THEN
        IF NEW.edition_id IS NULL
           OR NEW.retention_until IS NULL
           OR NEW.retention_until <= clock_timestamp()
           OR NOT public.maru_logistics_person_is_eligible(
                NEW.subject_account_id,
                NEW.created_by_id,
                NEW.organization_id,
                NEW.edition_id
           )
        THEN
            RAISE EXCEPTION 'restricted contact person is unavailable or out of scope'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.lifecycle = 'active' AND NEW.postal_address = '' THEN
        RAISE EXCEPTION 'active restricted contact requires a postal address'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.lifecycle = 'disposed' AND (
        NEW.subject_account_id IS NOT NULL
        OR NEW.party_id IS NOT NULL
        OR NEW.recipient_name <> ''
        OR NEW.contact_email <> ''
        OR NEW.contact_phone <> ''
        OR NEW.postal_address <> ''
        OR NEW.access_instructions <> ''
    ) THEN
        RAISE EXCEPTION 'disposed restricted contact retains sensitive values'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;
"""

CATALOG_SCOPE_SQL = r"""
CREATE FUNCTION public.maru_validate_logistics_catalog_scope()
RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'logistics_equipmentoffer' THEN
        IF TG_OP = 'INSERT' AND NOT EXISTS (
            SELECT 1
              FROM public.identity_account AS offerer
             WHERE offerer.id = NEW.offered_by_id
               AND offerer.account_kind = 'person'
               AND offerer.is_active
        ) THEN
            RAISE EXCEPTION 'equipment offer requires an active person offerer'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' OR NEW.status = 'accepted' THEN
            PERFORM 1
              FROM public.logistics_restrictedlogisticsaddress AS address
             WHERE address.id = NEW.pickup_address_id
               AND address.organization_id = NEW.organization_id
               AND (address.edition_id IS NULL OR address.edition_id = NEW.edition_id)
               AND address.subject_account_id = NEW.offered_by_id
               AND address.purpose = 'pickup'
               AND address.lifecycle = 'active'
               AND address.retention_until >= GREATEST(
                    NEW.available_until,
                    COALESCE(NEW.requested_return_at, NEW.available_until)
               )
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'equipment offer exact scope or pickup retention mismatch'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            PERFORM 1
              FROM public.logistics_restrictedlogisticsaddress AS address
             WHERE address.id = NEW.pickup_address_id
               AND address.organization_id = NEW.organization_id
               AND (address.edition_id IS NULL OR address.edition_id = NEW.edition_id)
               AND address.purpose = 'pickup'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'equipment offer historical pickup scope mismatch'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF TG_OP = 'UPDATE' AND (
            NEW.edition_id IS DISTINCT FROM OLD.edition_id
            OR NEW.offered_by_id IS DISTINCT FROM OLD.offered_by_id
            OR NEW.pickup_address_id IS DISTINCT FROM OLD.pickup_address_id
            OR NEW.title IS DISTINCT FROM OLD.title
            OR NEW.description IS DISTINCT FROM OLD.description
            OR NEW.available_from IS DISTINCT FROM OLD.available_from
            OR NEW.available_until IS DISTINCT FROM OLD.available_until
            OR NEW.requested_return_at IS DISTINCT FROM OLD.requested_return_at
        ) THEN
            RAISE EXCEPTION 'equipment offer submission facts are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (
            OLD.status <> 'pending'
            OR NEW.status NOT IN ('withdrawn', 'accepted', 'rejected')
            OR (
                NEW.status = 'withdrawn'
                AND (
                    NEW.reviewed_by_id IS NOT NULL
                    OR NEW.reviewed_at IS NOT NULL
                    OR NEW.review_reason <> ''
                    OR NEW.responsible_department_id IS NOT NULL
                )
            )
            OR (
                NEW.status = 'accepted'
                AND (
                    NEW.reviewed_by_id IS NULL
                    OR NEW.reviewed_at IS NULL
                    OR btrim(NEW.review_reason) = ''
                    OR NEW.responsible_department_id IS NULL
                )
            )
            OR (
                NEW.status = 'rejected'
                AND (
                    NEW.reviewed_by_id IS NULL
                    OR NEW.reviewed_at IS NULL
                    OR btrim(NEW.review_reason) = ''
                    OR NEW.responsible_department_id IS NOT NULL
                )
            )
            OR NEW.reviewed_by_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM public.identity_account AS reviewer
                 WHERE reviewer.id = NEW.reviewed_by_id
                   AND reviewer.account_kind = 'person'
                   AND reviewer.is_active
            )
        ) THEN
            RAISE EXCEPTION 'equipment offer update is not a closed review transition'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id
               AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'equipment offer edition scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.responsible_department_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.workforce_department AS department
             WHERE department.id = NEW.responsible_department_id
               AND department.organization_id = NEW.organization_id
               AND department.edition_id = NEW.edition_id
               AND department.retired_at IS NULL
        ) THEN
            RAISE EXCEPTION 'equipment offer Department scope mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_equipmentofferitem' THEN
        PERFORM 1
          FROM public.logistics_equipmentoffer AS offer
         WHERE offer.id = NEW.offer_id
           AND offer.status = 'pending'
           AND NOT EXISTS (
                SELECT 1
                  FROM public.logistics_equipmentofferhistory AS history
                 WHERE history.offer_id = offer.id
           )
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'equipment offer items may only extend a pending offer'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_equipmentofferhistory' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_equipmentoffer AS offer
             WHERE offer.id = NEW.offer_id
               AND offer.organization_id = NEW.organization_id
               AND offer.edition_id = NEW.edition_id
        ) THEN
            RAISE EXCEPTION 'equipment offer history scope mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_equipmentofferacceptance' THEN
        IF NOT EXISTS (
            SELECT 1
              FROM public.logistics_equipmentofferitem AS item
              JOIN public.logistics_equipmentoffer AS offer ON offer.id = item.offer_id
              LEFT JOIN public.logistics_asset AS asset ON asset.id = NEW.asset_id
              LEFT JOIN public.logistics_stocklot AS lot ON lot.id = NEW.stock_lot_id
             WHERE item.id = NEW.offer_item_id
               AND (
                    (
                        item.kind = 'serialized'
                        AND NEW.asset_id IS NOT NULL
                        AND NEW.stock_lot_id IS NULL
                        AND asset.organization_id = offer.organization_id
                        AND asset.edition_allocation_id = offer.edition_id
                        AND asset.owner_account_id = offer.offered_by_id
                    ) OR (
                        item.kind = 'bulk'
                        AND NEW.asset_id IS NULL
                        AND NEW.stock_lot_id IS NOT NULL
                        AND lot.organization_id = offer.organization_id
                        AND lot.edition_allocation_id = offer.edition_id
                        AND lot.owner_account_id = offer.offered_by_id
                    )
               )
        ) THEN
            RAISE EXCEPTION 'equipment offer acceptance subject scope mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_logisticsnode' THEN
        IF NEW.storage_address_id IS NOT NULL THEN
            PERFORM 1
              FROM public.logistics_restrictedlogisticsaddress AS address
             WHERE address.id = NEW.storage_address_id
               AND address.organization_id = NEW.organization_id
               AND address.purpose = 'storage'
               AND address.lifecycle = 'active'
               AND (
                    (NEW.edition_id IS NULL AND address.edition_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (
                        address.edition_id IS NULL OR address.edition_id = NEW.edition_id
                    ))
               )
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Logistics node storage-address scope mismatch'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF TG_OP = 'UPDATE' AND (
            NEW.edition_id IS DISTINCT FROM OLD.edition_id
            OR NEW.kind IS DISTINCT FROM OLD.kind
            OR NEW.code IS DISTINCT FROM OLD.code
            OR NEW.storage_address_id IS DISTINCT FROM OLD.storage_address_id
            OR NEW.external_owner_id IS DISTINCT FROM OLD.external_owner_id
            OR NEW.provider_id IS DISTINCT FROM OLD.provider_id
            OR NEW.venue_space_selection_id IS DISTINCT FROM OLD.venue_space_selection_id
        ) THEN
            RAISE EXCEPTION 'Logistics node type and exact allocation are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.edition_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id
               AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'Logistics node edition scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.storage_address_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_restrictedlogisticsaddress AS address
             WHERE address.id = NEW.storage_address_id
               AND address.organization_id = NEW.organization_id
               AND address.purpose = 'storage'
               AND address.lifecycle = 'active'
               AND (
                    (NEW.edition_id IS NULL AND address.edition_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (
                        address.edition_id IS NULL OR address.edition_id = NEW.edition_id
                    ))
               )
        ) THEN
            RAISE EXCEPTION 'Logistics node storage-address scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.external_owner_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsparty AS party
             WHERE party.id = NEW.external_owner_id
               AND party.organization_id = NEW.organization_id
               AND party.lifecycle = 'active'
               AND party.role IN ('owner', 'mixed')
        ) THEN
            RAISE EXCEPTION 'Logistics node owner scope or role mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.provider_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsparty AS party
             WHERE party.id = NEW.provider_id
               AND party.organization_id = NEW.organization_id
               AND party.lifecycle = 'active'
               AND party.role IN ('owner', 'provider', 'rental_business', 'mixed')
        ) THEN
            RAISE EXCEPTION 'Logistics node provider scope or role mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'venue_room' AND NOT EXISTS (
            SELECT 1 FROM public.venues_editionspaceselection AS selection
             WHERE selection.id = NEW.venue_space_selection_id
               AND selection.organization_id = NEW.organization_id
               AND selection.edition_id = NEW.edition_id
               AND selection.lifecycle = 'active'
        ) THEN
            RAISE EXCEPTION 'venue-room node selection scope mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME IN ('logistics_asset', 'logistics_stocklot') THEN
        IF TG_OP = 'UPDATE' AND (
            NEW.edition_allocation_id IS DISTINCT FROM OLD.edition_allocation_id
            OR NEW.owner_kind IS DISTINCT FROM OLD.owner_kind
            OR NEW.owner_account_id IS DISTINCT FROM OLD.owner_account_id
            OR NEW.owner_party_id IS DISTINCT FROM OLD.owner_party_id
            OR NEW.catalog_code IS DISTINCT FROM OLD.catalog_code
        ) THEN
            RAISE EXCEPTION 'inventory ownership and exact allocation are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.edition_allocation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_allocation_id
               AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'inventory edition allocation mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NOT (
            (NEW.owner_kind = 'organization' AND NEW.owner_account_id IS NULL AND NEW.owner_party_id IS NULL)
            OR (NEW.owner_kind = 'account' AND NEW.owner_account_id IS NOT NULL AND NEW.owner_party_id IS NULL)
            OR (NEW.owner_kind = 'external_party' AND NEW.owner_account_id IS NULL AND NEW.owner_party_id IS NOT NULL)
        ) THEN
            RAISE EXCEPTION 'inventory ownership shape mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.owner_account_id IS NOT NULL
           AND NOT public.maru_logistics_person_is_eligible(
                NEW.owner_account_id,
                NEW.created_by_id,
                NEW.organization_id,
                NEW.edition_allocation_id
           )
           AND NOT EXISTS (
                SELECT 1
                  FROM public.logistics_equipmentofferitem AS item
                  JOIN public.logistics_equipmentoffer AS offer
                    ON offer.id = item.offer_id
                  JOIN public.identity_account AS offerer
                    ON offerer.id = offer.offered_by_id
                 WHERE offer.organization_id = NEW.organization_id
                   AND offer.edition_id = NEW.edition_allocation_id
                   AND offer.offered_by_id = NEW.owner_account_id
                   AND offerer.account_kind = 'person'
                   AND offer.status = 'pending'
                   AND NEW.catalog_code = 'offer-' || replace(item.id::text, '-', '')
                   AND (
                        (TG_TABLE_NAME = 'logistics_asset' AND item.kind = 'serialized')
                        OR (TG_TABLE_NAME = 'logistics_stocklot' AND item.kind = 'bulk')
                   )
           )
        THEN
            RAISE EXCEPTION 'inventory person owner is unavailable or out of scope'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.owner_party_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsparty AS party
             WHERE party.id = NEW.owner_party_id
               AND party.organization_id = NEW.organization_id
               AND party.lifecycle = 'active'
               AND party.role IN ('owner', 'mixed')
        ) THEN
            RAISE EXCEPTION 'inventory external owner scope or role mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_physicalkey' THEN
        IF TG_OP = 'UPDATE' AND (
            NEW.edition_allocation_id IS DISTINCT FROM OLD.edition_allocation_id
            OR NEW.code IS DISTINCT FROM OLD.code
            OR NEW.opens_node_id IS DISTINCT FROM OLD.opens_node_id
            OR NEW.provider_id IS DISTINCT FROM OLD.provider_id
        ) THEN
            RAISE EXCEPTION 'physical-key lock and exact allocation are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.edition_allocation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_allocation_id
               AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'physical-key edition allocation mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsnode AS node
             WHERE node.id = NEW.opens_node_id
               AND node.organization_id = NEW.organization_id
               AND (
                    (NEW.edition_allocation_id IS NULL AND node.edition_id IS NULL)
                    OR (NEW.edition_allocation_id IS NOT NULL AND (
                        node.edition_id IS NULL OR node.edition_id = NEW.edition_allocation_id
                    ))
               )
        ) THEN
            RAISE EXCEPTION 'physical-key lock allocation mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.provider_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsparty AS party
             WHERE party.id = NEW.provider_id
               AND party.organization_id = NEW.organization_id
               AND party.lifecycle = 'active'
               AND party.role IN ('owner', 'provider', 'rental_business', 'mixed')
        ) THEN
            RAISE EXCEPTION 'physical-key provider scope or role mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_keyholderresponsibility' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_physicalkey AS key
             WHERE key.id = NEW.key_id
               AND public.maru_logistics_person_is_eligible(
                    NEW.responsible_account_id,
                    NEW.assigned_by_id,
                    key.organization_id,
                    key.edition_allocation_id
               )
        ) THEN
            RAISE EXCEPTION 'physical-key holder is unavailable or out of scope'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_assetagreement' THEN
        IF NEW.return_address_id IS NOT NULL THEN
            PERFORM 1
              FROM public.logistics_restrictedlogisticsaddress AS address
             WHERE address.id = NEW.return_address_id
               AND address.organization_id = NEW.organization_id
               AND address.purpose = 'return'
               AND address.lifecycle = 'active'
               AND address.retention_until IS NOT NULL
               AND address.retention_until >= NEW.return_due_at
               AND (
                    (NEW.edition_id IS NULL AND address.edition_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (
                        address.edition_id IS NULL OR address.edition_id = NEW.edition_id
                    ))
               )
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'agreement return-address scope or retention mismatch'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF NEW.aggregate_version <> 1 THEN
            RAISE EXCEPTION 'asset agreements start at version one'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.edition_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id
               AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'agreement edition scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF num_nonnulls(NEW.asset_id, NEW.stock_lot_id, NEW.physical_key_id, NEW.node_id) <> 1 THEN
            RAISE EXCEPTION 'agreement subject shape mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.asset_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_asset AS subject
             WHERE subject.id = NEW.asset_id
               AND subject.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND subject.edition_allocation_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = NEW.edition_id)))
        ) OR NEW.stock_lot_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_stocklot AS subject
             WHERE subject.id = NEW.stock_lot_id
               AND subject.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND subject.edition_allocation_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = NEW.edition_id)))
        ) OR NEW.physical_key_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_physicalkey AS subject
             WHERE subject.id = NEW.physical_key_id
               AND subject.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND subject.edition_allocation_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = NEW.edition_id)))
        ) OR NEW.node_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsnode AS subject
             WHERE subject.id = NEW.node_id
               AND subject.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND subject.edition_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (subject.edition_id IS NULL OR subject.edition_id = NEW.edition_id)))
        ) THEN
            RAISE EXCEPTION 'agreement subject exact scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF num_nonnulls(NEW.provider_id, NEW.provider_account_id) <> 1
           OR num_nonnulls(NEW.borrower_party_id, NEW.borrower_account_id) > 1
        THEN
            RAISE EXCEPTION 'agreement party shape mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.provider_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsparty AS party
             WHERE party.id = NEW.provider_id
               AND party.organization_id = NEW.organization_id
               AND party.lifecycle = 'active'
               AND party.role IN ('owner', 'provider', 'rental_business', 'mixed')
        ) OR NEW.borrower_party_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsparty AS party
             WHERE party.id = NEW.borrower_party_id
               AND party.organization_id = NEW.organization_id
               AND party.lifecycle = 'active'
               AND party.role IN ('borrower', 'mixed')
        ) THEN
            RAISE EXCEPTION 'agreement external party scope or role mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.provider_account_id IS NOT NULL
           AND NOT public.maru_logistics_person_is_eligible(
                NEW.provider_account_id,
                NEW.created_by_id,
                NEW.organization_id,
                NEW.edition_id
           )
           AND NOT EXISTS (
                SELECT 1 FROM public.identity_account AS account
                 WHERE account.id = NEW.provider_account_id
                   AND account.account_kind = 'person'
                   AND account.is_active
                   AND (
                        EXISTS (
                            SELECT 1 FROM public.logistics_asset AS subject
                             WHERE subject.id = NEW.asset_id
                               AND subject.owner_account_id = account.id
                        )
                        OR EXISTS (
                            SELECT 1 FROM public.logistics_stocklot AS subject
                             WHERE subject.id = NEW.stock_lot_id
                               AND subject.owner_account_id = account.id
                        )
                   )
           )
           AND NOT EXISTS (
                SELECT 1
                  FROM public.logistics_equipmentofferacceptance AS acceptance
                  JOIN public.logistics_equipmentofferitem AS item
                    ON item.id = acceptance.offer_item_id
                  JOIN public.logistics_equipmentoffer AS offer
                    ON offer.id = item.offer_id
                  JOIN public.identity_account AS offerer
                    ON offerer.id = offer.offered_by_id
                 WHERE acceptance.id = NEW.offer_acceptance_id
                   AND offer.organization_id = NEW.organization_id
                   AND offer.edition_id = NEW.edition_id
                   AND offer.offered_by_id = NEW.provider_account_id
                   AND offerer.account_kind = 'person'
           )
        OR NEW.borrower_account_id IS NOT NULL
           AND NOT public.maru_logistics_person_is_eligible(
                NEW.borrower_account_id,
                NEW.created_by_id,
                NEW.organization_id,
                NEW.edition_id
           )
           AND NOT EXISTS (
                SELECT 1 FROM public.identity_account AS account
                 WHERE account.id = NEW.borrower_account_id
                   AND account.account_kind = 'person'
                   AND account.is_active
                   AND (
                        EXISTS (
                            SELECT 1 FROM public.logistics_asset AS subject
                             WHERE subject.id = NEW.asset_id
                               AND subject.owner_account_id = account.id
                        )
                        OR EXISTS (
                            SELECT 1 FROM public.logistics_stocklot AS subject
                             WHERE subject.id = NEW.stock_lot_id
                               AND subject.owner_account_id = account.id
                        )
                   )
           )
        THEN
            RAISE EXCEPTION 'agreement person party is unavailable or out of scope'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.return_address_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_restrictedlogisticsaddress AS address
             WHERE address.id = NEW.return_address_id
               AND address.organization_id = NEW.organization_id
               AND address.purpose = 'return'
               AND address.lifecycle = 'active'
               AND address.retention_until IS NOT NULL
               AND address.retention_until >= NEW.return_due_at
               AND ((NEW.edition_id IS NULL AND address.edition_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (address.edition_id IS NULL OR address.edition_id = NEW.edition_id)))
        ) THEN
            RAISE EXCEPTION 'agreement return-address scope or retention mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_reusablekitline' THEN
        IF num_nonnulls(NEW.asset_id, NEW.stock_lot_id, NEW.physical_key_id) <> 1 THEN
            RAISE EXCEPTION 'kit-line subject shape mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_reusablekit AS kit
             WHERE kit.id = NEW.kit_id
               AND (
                    (NEW.asset_id IS NOT NULL AND EXISTS (SELECT 1 FROM public.logistics_asset AS subject WHERE subject.id = NEW.asset_id AND subject.organization_id = kit.organization_id))
                    OR (NEW.stock_lot_id IS NOT NULL AND EXISTS (SELECT 1 FROM public.logistics_stocklot AS subject WHERE subject.id = NEW.stock_lot_id AND subject.organization_id = kit.organization_id))
                    OR (NEW.physical_key_id IS NOT NULL AND EXISTS (SELECT 1 FROM public.logistics_physicalkey AS subject WHERE subject.id = NEW.physical_key_id AND subject.organization_id = kit.organization_id))
               )
        ) OR (NEW.stock_lot_id IS NULL AND NEW.quantity <> 1) THEN
            RAISE EXCEPTION 'kit-line subject scope or quantity mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_logisticsmanifest' THEN
        IF TG_OP = 'UPDATE' AND (
            NEW.edition_id IS DISTINCT FROM OLD.edition_id
            OR NEW.responsible_department_id IS DISTINCT FROM OLD.responsible_department_id
            OR NEW.manifest_number IS DISTINCT FROM OLD.manifest_number
            OR NEW.kind IS DISTINCT FROM OLD.kind
            OR NEW.source_node_id IS DISTINCT FROM OLD.source_node_id
            OR NEW.destination_node_id IS DISTINCT FROM OLD.destination_node_id
            OR NEW.vehicle_id IS DISTINCT FROM OLD.vehicle_id
            OR NEW.provider_id IS DISTINCT FROM OLD.provider_id
        ) THEN
            RAISE EXCEPTION 'manifest route and exact scope are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
        ) OR NOT EXISTS (
            SELECT 1 FROM public.workforce_department AS department
             WHERE department.id = NEW.responsible_department_id
               AND department.organization_id = NEW.organization_id
               AND department.edition_id = NEW.edition_id
               AND (TG_OP <> 'INSERT' OR department.retired_at IS NULL)
        ) THEN
            RAISE EXCEPTION 'manifest edition or Department scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.source_node_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsnode AS node WHERE node.id = NEW.source_node_id AND node.organization_id = NEW.organization_id AND (node.edition_id IS NULL OR node.edition_id = NEW.edition_id)
        ) OR NEW.destination_node_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsnode AS node WHERE node.id = NEW.destination_node_id AND node.organization_id = NEW.organization_id AND (node.edition_id IS NULL OR node.edition_id = NEW.edition_id)
        ) OR NEW.vehicle_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsnode AS node WHERE node.id = NEW.vehicle_id AND node.organization_id = NEW.organization_id AND (node.edition_id IS NULL OR node.edition_id = NEW.edition_id) AND node.kind = 'vehicle'
        ) THEN
            RAISE EXCEPTION 'manifest route node scope or type mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.provider_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsparty AS party
             WHERE party.id = NEW.provider_id AND party.organization_id = NEW.organization_id
               AND (TG_OP <> 'INSERT' OR party.lifecycle = 'active')
               AND party.role IN ('owner', 'provider', 'rental_business', 'mixed')
        ) THEN
            RAISE EXCEPTION 'manifest provider scope or role mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_logisticsmanifestline' THEN
        IF num_nonnulls(NEW.node_id, NEW.asset_id, NEW.stock_lot_id, NEW.physical_key_id) <> 1
           OR (NEW.subject_kind = 'node') IS DISTINCT FROM (NEW.node_id IS NOT NULL)
           OR (NEW.subject_kind = 'asset') IS DISTINCT FROM (NEW.asset_id IS NOT NULL)
           OR (NEW.subject_kind = 'stock_lot') IS DISTINCT FROM (NEW.stock_lot_id IS NOT NULL)
           OR (NEW.subject_kind = 'key') IS DISTINCT FROM (NEW.physical_key_id IS NOT NULL)
           OR (NEW.subject_kind <> 'stock_lot' AND NEW.quantity <> 1)
        THEN
            RAISE EXCEPTION 'manifest-line subject shape or quantity mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NOT (
            (NEW.node_id IS NOT NULL AND NEW.label_snapshot = (
                SELECT subject.name FROM public.logistics_logisticsnode AS subject
                 WHERE subject.id = NEW.node_id
            ))
            OR (NEW.asset_id IS NOT NULL AND NEW.label_snapshot = (
                SELECT subject.name FROM public.logistics_asset AS subject
                 WHERE subject.id = NEW.asset_id
            ))
            OR (NEW.stock_lot_id IS NOT NULL AND NEW.label_snapshot = (
                SELECT subject.name FROM public.logistics_stocklot AS subject
                 WHERE subject.id = NEW.stock_lot_id
            ))
            OR (NEW.physical_key_id IS NOT NULL AND NEW.label_snapshot = (
                SELECT subject.label FROM public.logistics_physicalkey AS subject
                 WHERE subject.id = NEW.physical_key_id
            ))
        ) THEN
            RAISE EXCEPTION 'manifest-line label snapshot must be server-derived'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsmanifest AS manifest
             WHERE manifest.id = NEW.manifest_id
               AND manifest.status = 'draft'
               AND (
                    (NEW.node_id IS NOT NULL AND EXISTS (SELECT 1 FROM public.logistics_logisticsnode AS subject WHERE subject.id = NEW.node_id AND subject.organization_id = manifest.organization_id AND (subject.edition_id IS NULL OR subject.edition_id = manifest.edition_id)))
                    OR (NEW.asset_id IS NOT NULL AND EXISTS (SELECT 1 FROM public.logistics_asset AS subject WHERE subject.id = NEW.asset_id AND subject.organization_id = manifest.organization_id AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = manifest.edition_id)))
                    OR (NEW.stock_lot_id IS NOT NULL AND EXISTS (SELECT 1 FROM public.logistics_stocklot AS subject WHERE subject.id = NEW.stock_lot_id AND subject.organization_id = manifest.organization_id AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = manifest.edition_id)))
                    OR (NEW.physical_key_id IS NOT NULL AND EXISTS (SELECT 1 FROM public.logistics_physicalkey AS subject WHERE subject.id = NEW.physical_key_id AND subject.organization_id = manifest.organization_id AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = manifest.edition_id)))
               )
               AND (NEW.packed_in_node_id IS NULL OR EXISTS (
                    SELECT 1 FROM public.logistics_logisticsnode AS packed
                     WHERE packed.id = NEW.packed_in_node_id
                       AND packed.organization_id = manifest.organization_id
                       AND (packed.edition_id IS NULL OR packed.edition_id = manifest.edition_id)
                       AND packed.kind IN ('box', 'container', 'vehicle')
               ))
        ) THEN
            RAISE EXCEPTION 'manifest-line subject or packed-node scope mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_logisticslabel' THEN
        IF TG_OP = 'UPDATE' AND (
            NEW.label_code IS DISTINCT FROM OLD.label_code
            OR NEW.qr_identifier_digest IS DISTINCT FROM OLD.qr_identifier_digest
            OR NEW.node_id IS DISTINCT FROM OLD.node_id
            OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
            OR NEW.stock_lot_id IS DISTINCT FROM OLD.stock_lot_id
            OR NEW.physical_key_id IS DISTINCT FROM OLD.physical_key_id
        ) THEN
            RAISE EXCEPTION 'Logistics label identity and subject are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF num_nonnulls(NEW.node_id, NEW.asset_id, NEW.stock_lot_id, NEW.physical_key_id) <> 1
           OR NEW.node_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_logisticsnode AS subject WHERE subject.id = NEW.node_id AND subject.organization_id = NEW.organization_id)
           OR NEW.asset_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_asset AS subject WHERE subject.id = NEW.asset_id AND subject.organization_id = NEW.organization_id)
           OR NEW.stock_lot_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_stocklot AS subject WHERE subject.id = NEW.stock_lot_id AND subject.organization_id = NEW.organization_id)
           OR NEW.physical_key_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_physicalkey AS subject WHERE subject.id = NEW.physical_key_id AND subject.organization_id = NEW.organization_id)
        THEN
            RAISE EXCEPTION 'Logistics label subject scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;
"""

EVIDENCE_SCOPE_SQL = r"""
CREATE FUNCTION public.maru_validate_logistics_evidence_scope()
RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'logistics_logisticsevent' THEN
        IF NEW.event_type NOT IN (
            'receive', 'pack', 'unpack', 'move', 'load', 'unload',
            'handover', 'count', 'condition', 'damage', 'return'
        ) OR NEW.subject_kind NOT IN ('node', 'asset', 'stock_lot', 'key') THEN
            RAISE EXCEPTION 'Logistics event discriminator is unavailable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.edition_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id
               AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'Logistics event edition scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF num_nonnulls(NEW.node_id, NEW.asset_id, NEW.stock_lot_id, NEW.physical_key_id) <> 1
           OR (NEW.subject_kind = 'node') IS DISTINCT FROM (NEW.node_id IS NOT NULL)
           OR (NEW.subject_kind = 'asset') IS DISTINCT FROM (NEW.asset_id IS NOT NULL)
           OR (NEW.subject_kind = 'stock_lot') IS DISTINCT FROM (NEW.stock_lot_id IS NOT NULL)
           OR (NEW.subject_kind = 'key') IS DISTINCT FROM (NEW.physical_key_id IS NOT NULL)
        THEN
            RAISE EXCEPTION 'Logistics event subject shape mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.node_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsnode AS subject
             WHERE subject.id = NEW.node_id
               AND subject.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND subject.edition_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (subject.edition_id IS NULL OR subject.edition_id = NEW.edition_id)))
        ) OR NEW.asset_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_asset AS subject
             WHERE subject.id = NEW.asset_id
               AND subject.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND subject.edition_allocation_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = NEW.edition_id)))
        ) OR NEW.stock_lot_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_stocklot AS subject
             WHERE subject.id = NEW.stock_lot_id
               AND subject.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND subject.edition_allocation_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = NEW.edition_id)))
        ) OR NEW.physical_key_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_physicalkey AS subject
             WHERE subject.id = NEW.physical_key_id
               AND subject.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND subject.edition_allocation_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (subject.edition_allocation_id IS NULL OR subject.edition_allocation_id = NEW.edition_id)))
        ) THEN
            RAISE EXCEPTION 'Logistics event subject exact scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.source_node_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsnode AS node
             WHERE node.id = NEW.source_node_id AND node.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND node.edition_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (node.edition_id IS NULL OR node.edition_id = NEW.edition_id)))
        ) OR NEW.destination_node_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsnode AS node
             WHERE node.id = NEW.destination_node_id AND node.organization_id = NEW.organization_id
               AND ((NEW.edition_id IS NULL AND node.edition_id IS NULL)
                    OR (NEW.edition_id IS NOT NULL AND (node.edition_id IS NULL OR node.edition_id = NEW.edition_id)))
        ) THEN
            RAISE EXCEPTION 'Logistics event location scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.manifest_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
              FROM public.logistics_logisticsmanifest AS manifest
              JOIN public.logistics_logisticsmanifestline AS line
                ON line.manifest_id = manifest.id
               AND line.node_id IS NOT DISTINCT FROM NEW.node_id
               AND line.asset_id IS NOT DISTINCT FROM NEW.asset_id
               AND line.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
               AND line.physical_key_id IS NOT DISTINCT FROM NEW.physical_key_id
             WHERE manifest.id = NEW.manifest_id
               AND manifest.organization_id = NEW.organization_id
               AND manifest.edition_id = NEW.edition_id
               AND manifest.status IN ('sealed', 'completed')
               AND (
                    line.stock_lot_id IS NULL
                    OR NEW.quantity = line.quantity
               )
               AND NEW.evidence_reference = 'manifest-line:' || line.id::text
               AND (
                    (
                        NEW.event_type = 'receive'
                        AND manifest.kind IN ('inbound', 'stage_receiving')
                        AND NEW.source_node_id IS NULL
                        AND COALESCE(line.packed_in_node_id, manifest.destination_node_id) IS NOT NULL
                        AND NEW.destination_node_id = COALESCE(line.packed_in_node_id, manifest.destination_node_id)
                    )
                    OR (
                        NEW.event_type = 'load'
                        AND manifest.kind IN ('outbound', 'transfer', 'return')
                        AND manifest.source_node_id IS NOT NULL
                        AND manifest.vehicle_id IS NOT NULL
                        AND NEW.source_node_id = manifest.source_node_id
                        AND NEW.destination_node_id = manifest.vehicle_id
                    )
                    OR (
                        NEW.event_type = 'unload'
                        AND manifest.kind IN ('outbound', 'transfer', 'return')
                        AND manifest.vehicle_id IS NOT NULL
                        AND COALESCE(line.packed_in_node_id, manifest.destination_node_id) IS NOT NULL
                        AND NEW.source_node_id = manifest.vehicle_id
                        AND NEW.destination_node_id = COALESCE(line.packed_in_node_id, manifest.destination_node_id)
                    )
                    OR (
                        NEW.event_type = 'return'
                        AND manifest.kind = 'return'
                        AND manifest.source_node_id IS NOT NULL
                        AND COALESCE(line.packed_in_node_id, manifest.destination_node_id) IS NOT NULL
                        AND NEW.source_node_id = manifest.source_node_id
                        AND NEW.destination_node_id = COALESCE(line.packed_in_node_id, manifest.destination_node_id)
                    )
               )
        ) THEN
            RAISE EXCEPTION 'Logistics event manifest subject or declared route mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF num_nonnulls(NEW.from_custodian_account_id, NEW.from_custodian_party_id) > 1
           OR num_nonnulls(NEW.to_custodian_account_id, NEW.to_custodian_party_id) > 1
           OR NEW.from_custodian_party_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM public.logistics_logisticsparty AS party
                 WHERE party.id = NEW.from_custodian_party_id AND party.organization_id = NEW.organization_id
           )
           OR NEW.to_custodian_party_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM public.logistics_logisticsparty AS party
                 WHERE party.id = NEW.to_custodian_party_id
                   AND party.organization_id = NEW.organization_id
                   AND (
                        party.lifecycle = 'active'
                        OR (
                            NEW.event_type NOT IN ('receive', 'handover', 'return')
                            AND EXISTS (
                                SELECT 1
                                  FROM public.logistics_logisticscurrentstate AS state
                                 WHERE state.organization_id = NEW.organization_id
                                   AND state.node_id IS NOT DISTINCT FROM NEW.node_id
                                   AND state.asset_id IS NOT DISTINCT FROM NEW.asset_id
                                   AND state.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
                                   AND state.physical_key_id IS NOT DISTINCT FROM NEW.physical_key_id
                                   AND state.event_sequence = NEW.event_sequence - 1
                                   AND state.custodian_party_id = party.id
                            )
                        )
                   )
           )
           OR NEW.from_custodian_account_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM public.identity_account AS account
                 WHERE account.id = NEW.from_custodian_account_id
                   AND account.account_kind = 'person'
           )
           OR NEW.to_custodian_account_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM public.identity_account AS account
                 WHERE account.id = NEW.to_custodian_account_id
                   AND account.account_kind = 'person'
                   AND (
                        (
                            account.is_active
                            AND (
                                public.maru_logistics_person_is_eligible(
                                    account.id,
                                    NEW.actor_id,
                                    NEW.organization_id,
                                    NEW.edition_id
                                )
                                OR EXISTS (
                                    SELECT 1 FROM public.logistics_asset AS subject
                                     WHERE subject.id = NEW.asset_id
                                       AND subject.owner_account_id = account.id
                                )
                                OR EXISTS (
                                    SELECT 1 FROM public.logistics_stocklot AS subject
                                     WHERE subject.id = NEW.stock_lot_id
                                       AND subject.owner_account_id = account.id
                                )
                            )
                        )
                        OR (
                            NEW.event_type NOT IN ('receive', 'handover', 'return')
                            AND EXISTS (
                                SELECT 1
                                  FROM public.logistics_logisticscurrentstate AS state
                                 WHERE state.organization_id = NEW.organization_id
                                   AND state.node_id IS NOT DISTINCT FROM NEW.node_id
                                   AND state.asset_id IS NOT DISTINCT FROM NEW.asset_id
                                   AND state.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
                                   AND state.physical_key_id IS NOT DISTINCT FROM NEW.physical_key_id
                                   AND state.event_sequence = NEW.event_sequence - 1
                                   AND state.custodian_account_id = account.id
                            )
                        )
                   )
           )
        THEN
            RAISE EXCEPTION 'Logistics event custodian scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.subject_kind = 'stock_lot' AND NEW.quantity IS NULL
           OR NEW.subject_kind <> 'stock_lot' AND NEW.quantity IS NOT NULL AND NEW.quantity <> 1
        THEN
            RAISE EXCEPTION 'Logistics event quantity shape mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.event_type = 'receive'
           AND NEW.stock_lot_id IS NOT NULL
           AND NEW.quantity > (
                SELECT lot.initial_quantity
                  FROM public.logistics_stocklot AS lot
                 WHERE lot.id = NEW.stock_lot_id
           )
        THEN
            RAISE EXCEPTION 'received stock quantity exceeds its registered lot'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.event_type IN ('receive', 'pack', 'unpack', 'move', 'load', 'unload')
           AND NEW.destination_node_id IS NULL
        THEN
            RAISE EXCEPTION 'moving Logistics event requires a destination'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.event_type IN ('count', 'condition', 'damage', 'handover')
           AND NEW.destination_node_id IS NOT NULL
        THEN
            RAISE EXCEPTION 'non-moving Logistics event cannot have a destination'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.event_type = 'handover'
           AND NEW.to_custodian_account_id IS NULL
           AND NEW.to_custodian_party_id IS NULL
        THEN
            RAISE EXCEPTION 'handover requires a recipient'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.event_type = 'return'
           AND NEW.destination_node_id IS NULL
           AND NEW.to_custodian_account_id IS NULL
           AND NEW.to_custodian_party_id IS NULL
        THEN
            RAISE EXCEPTION 'return requires a destination or recipient'
                USING ERRCODE = '23514';
        END IF;
        IF btrim(NEW.condition_after) = '' THEN
            RAISE EXCEPTION 'Logistics events require a resulting condition'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.event_type = 'receive' AND NEW.event_sequence <> 1 THEN
            RAISE EXCEPTION 'receive is only valid as the first Logistics event'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.event_sequence = 1 THEN
            IF NEW.event_type <> 'receive'
               OR NEW.source_node_id IS NOT NULL
               OR NEW.from_custodian_account_id IS NOT NULL
               OR NEW.from_custodian_party_id IS NOT NULL
               OR NEW.condition_before <> ''
               OR btrim(NEW.condition_after) = ''
               OR EXISTS (
                SELECT 1 FROM public.logistics_logisticscurrentstate AS state
                 WHERE state.node_id IS NOT DISTINCT FROM NEW.node_id
                   AND state.asset_id IS NOT DISTINCT FROM NEW.asset_id
                   AND state.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
                   AND state.physical_key_id IS NOT DISTINCT FROM NEW.physical_key_id
            ) THEN
                RAISE EXCEPTION 'first Logistics event must receive an untracked subject'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticscurrentstate AS state
             WHERE state.organization_id = NEW.organization_id
               AND state.node_id IS NOT DISTINCT FROM NEW.node_id
               AND state.asset_id IS NOT DISTINCT FROM NEW.asset_id
               AND state.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
               AND state.physical_key_id IS NOT DISTINCT FROM NEW.physical_key_id
               AND state.event_sequence = NEW.event_sequence - 1
               AND state.current_node_id IS NOT DISTINCT FROM NEW.source_node_id
               AND state.custodian_account_id IS NOT DISTINCT FROM NEW.from_custodian_account_id
               AND state.custodian_party_id IS NOT DISTINCT FROM NEW.from_custodian_party_id
               AND state.condition IS NOT DISTINCT FROM NEW.condition_before
               AND (
                    NEW.stock_lot_id IS NULL
                    OR NEW.event_type = 'count'
                    OR state.quantity_on_hand IS NOT DISTINCT FROM NEW.quantity
               )
        ) THEN
            RAISE EXCEPTION 'Logistics event does not continue its prior projection'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_logisticsdiscrepancy' THEN
        IF TG_OP = 'UPDATE' AND (
            NEW.edition_id IS DISTINCT FROM OLD.edition_id
            OR NEW.kind IS DISTINCT FROM OLD.kind
            OR NEW.subject_kind IS DISTINCT FROM OLD.subject_kind
            OR NEW.subject_id IS DISTINCT FROM OLD.subject_id
            OR NEW.detected_event_id IS DISTINCT FROM OLD.detected_event_id
        ) THEN
            RAISE EXCEPTION 'Logistics discrepancy source facts are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.edition_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
        ) OR NEW.detected_event_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsevent AS event
             WHERE event.id = NEW.detected_event_id
               AND event.organization_id = NEW.organization_id
               AND event.edition_id IS NOT DISTINCT FROM NEW.edition_id
               AND CASE NEW.subject_kind
                    WHEN 'node' THEN event.node_id = NEW.subject_id
                    WHEN 'asset' THEN event.asset_id = NEW.subject_id
                    WHEN 'stock_lot' THEN event.stock_lot_id = NEW.subject_id
                    WHEN 'key' THEN event.physical_key_id = NEW.subject_id
                    ELSE FALSE
               END
        ) THEN
            RAISE EXCEPTION 'Logistics discrepancy exact scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.kind IN ('count', 'damage') AND NEW.detected_event_id IS NULL THEN
            RAISE EXCEPTION 'count and damage discrepancies require source events'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.detected_event_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
              FROM public.logistics_logisticsevent AS event
              LEFT JOIN public.logistics_logisticsevent AS prior
                ON prior.stock_lot_id = event.stock_lot_id
               AND prior.event_sequence = event.event_sequence - 1
             WHERE event.id = NEW.detected_event_id
               AND (
                    (
                        NEW.kind = 'count'
                        AND event.event_type = 'count'
                        AND event.stock_lot_id IS NOT NULL
                        AND prior.id IS NOT NULL
                        AND prior.quantity IS DISTINCT FROM event.quantity
                        AND NEW.expected_quantity IS NOT DISTINCT FROM prior.quantity
                        AND NEW.observed_quantity IS NOT DISTINCT FROM event.quantity
                    )
                    OR (
                        NEW.kind = 'damage'
                        AND event.event_type = 'damage'
                        AND (
                            (
                                event.stock_lot_id IS NOT NULL
                                AND NEW.expected_quantity IS NOT DISTINCT FROM prior.quantity
                                AND NEW.observed_quantity IS NOT DISTINCT FROM event.quantity
                            )
                            OR (
                                event.stock_lot_id IS NULL
                                AND NEW.expected_quantity IS NULL
                                AND NEW.observed_quantity IS NULL
                            )
                        )
                    )
               )
        ) THEN
            RAISE EXCEPTION 'Logistics discrepancy does not match its source event'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_logisticseditioncontrol' THEN
        IF TG_OP = 'UPDATE' AND NEW.edition_id IS DISTINCT FROM OLD.edition_id THEN
            RAISE EXCEPTION 'Logistics edition control scope is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'Logistics edition control scope mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_offlinescanbatch' THEN
        IF TG_OP = 'INSERT' AND (
            NEW.expires_at <= NEW.created_at
            OR NOT EXISTS (
                SELECT 1
                  FROM public.identity_account AS submitter
                 WHERE submitter.id = NEW.submitted_by_id
                   AND submitter.account_kind = 'person'
                   AND submitter.is_active
            )
            OR NEW.snapshot_version > COALESCE(
                (
                    SELECT control.aggregate_version
                      FROM public.logistics_logisticseditioncontrol AS control
                     WHERE control.organization_id = NEW.organization_id
                       AND control.edition_id = NEW.edition_id
                ),
                0
            )
        ) THEN
            RAISE EXCEPTION 'offline Logistics batch snapshot or lifetime is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (
            NEW.edition_id IS DISTINCT FROM OLD.edition_id
            OR NEW.device_code IS DISTINCT FROM OLD.device_code
            OR NEW.snapshot_version IS DISTINCT FROM OLD.snapshot_version
            OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
            OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
            OR NEW.operation_count IS DISTINCT FROM OLD.operation_count
            OR NEW.payload_digest IS DISTINCT FROM OLD.payload_digest
            OR NEW.submitted_by_id IS DISTINCT FROM OLD.submitted_by_id
        ) THEN
            RAISE EXCEPTION 'offline Logistics batch source facts are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (
            OLD.status <> 'pending'
            OR OLD.aggregate_version <> 1
            OR NEW.status NOT IN ('applied', 'review')
            OR NEW.aggregate_version <> 2
            OR NEW.expires_at <= clock_timestamp()
            OR (
                SELECT count(*)
                  FROM public.logistics_offlinescanoperation AS operation
                 WHERE operation.batch_id = NEW.id
            ) <> NEW.operation_count
            OR (
                SELECT min(operation.sequence)
                  FROM public.logistics_offlinescanoperation AS operation
                 WHERE operation.batch_id = NEW.id
            ) <> 1
            OR (
                SELECT max(operation.sequence)
                  FROM public.logistics_offlinescanoperation AS operation
                 WHERE operation.batch_id = NEW.id
            ) <> NEW.operation_count
            OR (
                NEW.status = 'applied'
                AND EXISTS (
                    SELECT 1
                      FROM public.logistics_offlinescanoperation AS operation
                     WHERE operation.batch_id = NEW.id
                       AND (
                            operation.result NOT IN ('applied', 'duplicate')
                            OR operation.discrepancy_id IS NOT NULL
                       )
                )
            )
            OR (
                NEW.status = 'review'
                AND NOT EXISTS (
                    SELECT 1
                      FROM public.logistics_offlinescanoperation AS operation
                     WHERE operation.batch_id = NEW.id
                       AND (
                            operation.result NOT IN ('applied', 'duplicate')
                            OR operation.discrepancy_id IS NOT NULL
                       )
                )
            )
        ) THEN
            RAISE EXCEPTION 'offline Logistics batch must close one complete reconciliation'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'offline Logistics batch scope mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_offlinescanoperation' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_offlinescanbatch AS batch
             WHERE batch.id = NEW.batch_id
               AND batch.status = 'pending'
               AND NEW.sequence BETWEEN 1 AND batch.operation_count
               AND NEW.occurred_at <= batch.created_at
               AND (NEW.applied_event_id IS NULL OR EXISTS (
                    SELECT 1 FROM public.logistics_logisticsevent AS event
                     WHERE event.id = NEW.applied_event_id
                       AND event.organization_id = batch.organization_id
                       AND event.edition_id = batch.edition_id
               ))
               AND (NEW.discrepancy_id IS NULL OR EXISTS (
                    SELECT 1 FROM public.logistics_logisticsdiscrepancy AS discrepancy
                     WHERE discrepancy.id = NEW.discrepancy_id
                       AND discrepancy.organization_id = batch.organization_id
                       AND discrepancy.edition_id = batch.edition_id
               ))
        ) THEN
            RAISE EXCEPTION 'offline Logistics operation scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.result = 'review'
           AND NEW.reason_code = 'logistics_offline_state_conflict'
           AND EXISTS (
                SELECT 1
                  FROM public.logistics_offlinescanbatch AS batch
                  JOIN public.logistics_logisticslabel AS subject_label
                    ON subject_label.organization_id = batch.organization_id
                   AND subject_label.label_code = NEW.label_code
                   AND subject_label.lifecycle = 'active'
                  LEFT JOIN public.logistics_logisticsnode AS subject_node
                    ON subject_node.id = subject_label.node_id
                  LEFT JOIN public.logistics_asset AS subject_asset
                    ON subject_asset.id = subject_label.asset_id
                  LEFT JOIN public.logistics_stocklot AS subject_lot
                    ON subject_lot.id = subject_label.stock_lot_id
                  LEFT JOIN public.logistics_physicalkey AS subject_key
                    ON subject_key.id = subject_label.physical_key_id
                  LEFT JOIN public.logistics_logisticscurrentstate AS state
                    ON state.organization_id = batch.organization_id
                   AND (
                        state.node_id = subject_label.node_id
                        OR state.asset_id = subject_label.asset_id
                        OR state.stock_lot_id = subject_label.stock_lot_id
                        OR state.physical_key_id = subject_label.physical_key_id
                   )
                  LEFT JOIN public.logistics_logisticsnode AS current_node
                    ON current_node.id = state.current_node_id
                  LEFT JOIN public.logistics_logisticslabel AS source_label
                    ON NEW.source_label_code <> ''
                   AND source_label.organization_id = batch.organization_id
                   AND source_label.label_code = NEW.source_label_code
                   AND source_label.lifecycle = 'active'
                   AND source_label.node_id IS NOT NULL
                  LEFT JOIN public.logistics_logisticsnode AS source_node
                    ON source_node.id = source_label.node_id
                  LEFT JOIN public.logistics_logisticslabel AS destination_label
                    ON NEW.destination_label_code <> ''
                   AND destination_label.organization_id = batch.organization_id
                   AND destination_label.label_code = NEW.destination_label_code
                   AND destination_label.lifecycle = 'active'
                   AND destination_label.node_id IS NOT NULL
                  LEFT JOIN public.logistics_logisticsnode AS destination_node
                    ON destination_node.id = destination_label.node_id
                 WHERE batch.id = NEW.batch_id
                   AND (
                        (
                            subject_node.id IS NOT NULL
                            AND subject_node.organization_id = batch.organization_id
                            AND (
                                subject_node.edition_id IS NULL
                                OR subject_node.edition_id = batch.edition_id
                            )
                        )
                        OR (
                            subject_asset.id IS NOT NULL
                            AND subject_asset.organization_id = batch.organization_id
                            AND (
                                subject_asset.edition_allocation_id IS NULL
                                OR subject_asset.edition_allocation_id = batch.edition_id
                            )
                        )
                        OR (
                            subject_lot.id IS NOT NULL
                            AND subject_lot.organization_id = batch.organization_id
                            AND (
                                subject_lot.edition_allocation_id IS NULL
                                OR subject_lot.edition_allocation_id = batch.edition_id
                            )
                        )
                        OR (
                            subject_key.id IS NOT NULL
                            AND subject_key.organization_id = batch.organization_id
                            AND (
                                subject_key.edition_allocation_id IS NULL
                                OR subject_key.edition_allocation_id = batch.edition_id
                            )
                        )
                   )
                   AND (
                        current_node.id IS NULL
                        OR (
                            current_node.organization_id = batch.organization_id
                            AND (
                                current_node.edition_id IS NULL
                                OR current_node.edition_id = batch.edition_id
                            )
                        )
                   )
                   AND (
                        NEW.source_label_code = ''
                        OR (
                            source_node.id IS NOT NULL
                            AND source_node.organization_id = batch.organization_id
                            AND (
                                source_node.edition_id IS NULL
                                OR source_node.edition_id = batch.edition_id
                            )
                        )
                   )
                   AND (
                        NEW.destination_label_code = ''
                        OR (
                            destination_node.id IS NOT NULL
                            AND destination_node.organization_id = batch.organization_id
                            AND (
                                destination_node.edition_id IS NULL
                                OR destination_node.edition_id = batch.edition_id
                            )
                        )
                   )
                   AND NEW.expected_subject_sequence = COALESCE(state.event_sequence, 0)
                   AND (
                        (state.id IS NULL AND NEW.action = 'receive')
                        OR (state.id IS NOT NULL AND NEW.action <> 'receive')
                   )
                   AND (
                        NEW.source_label_code = ''
                        OR source_node.id = state.current_node_id
                   )
                   AND (
                        (
                            NEW.action IN (
                                'receive', 'pack', 'unpack', 'move', 'load', 'unload'
                            )
                            AND destination_node.id IS NOT NULL
                        )
                        OR (
                            NEW.action IN ('count', 'condition', 'damage')
                            AND NEW.source_label_code = ''
                            AND NEW.destination_label_code = ''
                        )
                        OR (
                            NEW.action = 'return'
                            AND destination_node.id IS NOT NULL
                        )
                   )
                   AND (
                        subject_node.id IS NULL
                        OR destination_node.id IS NULL
                        OR CASE subject_node.kind
                            WHEN 'storage_site' THEN FALSE
                            WHEN 'storage_area' THEN destination_node.kind IN (
                                'storage_site', 'venue_room'
                            )
                            WHEN 'rack' THEN destination_node.kind IN (
                                'storage_area', 'container'
                            )
                            WHEN 'container' THEN destination_node.kind IN (
                                'storage_site', 'storage_area', 'vehicle',
                                'loading_zone', 'staging_area', 'venue_room'
                            )
                            WHEN 'box' THEN destination_node.kind IN (
                                'storage_area', 'rack', 'container', 'box', 'vehicle',
                                'loading_zone', 'staging_area', 'venue_room'
                            )
                            WHEN 'vehicle' THEN destination_node.kind IN (
                                'storage_site', 'loading_zone', 'staging_area'
                            )
                            WHEN 'loading_zone' THEN destination_node.kind IN (
                                'storage_site', 'venue_room'
                            )
                            WHEN 'staging_area' THEN destination_node.kind IN (
                                'storage_site', 'loading_zone', 'venue_room'
                            )
                            WHEN 'venue_room' THEN FALSE
                            ELSE FALSE
                        END
                   )
                   AND (
                        subject_node.id IS NULL
                        OR destination_node.id IS NULL
                        OR NOT EXISTS (
                            WITH RECURSIVE ancestors(id, depth) AS (
                                SELECT destination_node.id, 1
                                UNION ALL
                                SELECT ancestor_state.current_node_id, ancestors.depth + 1
                                  FROM public.logistics_logisticscurrentstate AS ancestor_state
                                  JOIN ancestors ON ancestor_state.node_id = ancestors.id
                                 WHERE ancestor_state.current_node_id IS NOT NULL
                                   AND ancestors.depth < 128
                            )
                            SELECT 1
                              FROM ancestors
                             WHERE id = subject_node.id OR depth >= 128
                        )
                   )
                   AND (
                        NEW.action NOT IN ('receive', 'damage')
                        OR btrim(NEW.observed_condition) <> ''
                   )
                   AND (
                        (
                            subject_lot.id IS NOT NULL
                            AND NEW.quantity IS NOT NULL
                            AND (
                                (
                                    NEW.action = 'receive'
                                    AND NEW.quantity <= subject_lot.initial_quantity
                                )
                                OR NEW.action = 'count'
                                OR (
                                    NEW.action NOT IN ('receive', 'count')
                                    AND NEW.quantity = state.quantity_on_hand
                                )
                            )
                        )
                        OR (
                            subject_lot.id IS NULL
                            AND (NEW.quantity IS NULL OR NEW.quantity = 1)
                        )
                   )
           )
        THEN
            RAISE EXCEPTION 'offline state-conflict review remains appendable'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_offlineoperationreceipt' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
        ) OR NEW.applied_event_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsevent AS event
             WHERE event.id = NEW.applied_event_id AND event.organization_id = NEW.organization_id AND event.edition_id = NEW.edition_id
        ) OR NEW.discrepancy_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsdiscrepancy AS discrepancy
             WHERE discrepancy.id = NEW.discrepancy_id AND discrepancy.organization_id = NEW.organization_id AND discrepancy.edition_id = NEW.edition_id
        ) THEN
            RAISE EXCEPTION 'offline Logistics receipt scope mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'logistics_logisticscommandreceipt' THEN
        IF NEW.edition_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.events_eventedition AS edition
             WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
        ) THEN
            RAISE EXCEPTION 'Logistics command receipt scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;
"""

STATE_FUNCTION_SQL = r"""
CREATE FUNCTION public.maru_guard_logistics_current_state()
RETURNS trigger AS $$
DECLARE
    cycle_found boolean;
    depth_exceeded boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'current Logistics state is retained with its event history'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.node_id IS DISTINCT FROM OLD.node_id
        OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
        OR NEW.stock_lot_id IS DISTINCT FROM OLD.stock_lot_id
        OR NEW.physical_key_id IS DISTINCT FROM OLD.physical_key_id
        OR NEW.event_sequence <> OLD.event_sequence + 1
    ) THEN
        RAISE EXCEPTION 'current Logistics projection advances one event for one subject'
            USING ERRCODE = '23514';
    END IF;
    IF num_nonnulls(NEW.node_id, NEW.asset_id, NEW.stock_lot_id, NEW.physical_key_id) <> 1
       OR num_nonnulls(NEW.custodian_account_id, NEW.custodian_party_id) > 1
       OR (NEW.stock_lot_id IS NOT NULL) IS DISTINCT FROM (NEW.quantity_on_hand IS NOT NULL)
    THEN
        RAISE EXCEPTION 'current Logistics state subject, custody, or quantity shape mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.node_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_logisticsnode AS subject WHERE subject.id = NEW.node_id AND subject.organization_id = NEW.organization_id)
       OR NEW.asset_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_asset AS subject WHERE subject.id = NEW.asset_id AND subject.organization_id = NEW.organization_id)
       OR NEW.stock_lot_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_stocklot AS subject WHERE subject.id = NEW.stock_lot_id AND subject.organization_id = NEW.organization_id)
       OR NEW.physical_key_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_physicalkey AS subject WHERE subject.id = NEW.physical_key_id AND subject.organization_id = NEW.organization_id)
       OR NEW.current_node_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_logisticsnode AS node WHERE node.id = NEW.current_node_id AND node.organization_id = NEW.organization_id)
       OR NEW.custodian_party_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.logistics_logisticsparty AS party WHERE party.id = NEW.custodian_party_id AND party.organization_id = NEW.organization_id)
       OR NEW.custodian_account_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.identity_account AS account
             WHERE account.id = NEW.custodian_account_id
               AND account.account_kind = 'person'
       )
    THEN
        RAISE EXCEPTION 'current Logistics state tenant scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.logistics_logisticsevent AS event
         WHERE event.id = NEW.last_event_id
           AND event.organization_id = NEW.organization_id
           AND event.node_id IS NOT DISTINCT FROM NEW.node_id
           AND event.asset_id IS NOT DISTINCT FROM NEW.asset_id
           AND event.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
           AND event.physical_key_id IS NOT DISTINCT FROM NEW.physical_key_id
           AND event.event_sequence = NEW.event_sequence
           AND NEW.current_node_id IS NOT DISTINCT FROM CASE
                WHEN event.event_type IN ('receive', 'pack', 'unpack', 'move', 'load', 'unload', 'return') THEN event.destination_node_id
                ELSE event.source_node_id
           END
           AND event.to_custodian_account_id IS NOT DISTINCT FROM NEW.custodian_account_id
           AND event.to_custodian_party_id IS NOT DISTINCT FROM NEW.custodian_party_id
           AND event.condition_after IS NOT DISTINCT FROM NEW.condition
           AND (NEW.stock_lot_id IS NULL OR event.quantity IS NOT DISTINCT FROM NEW.quantity_on_hand)
           AND NEW.state = CASE
                WHEN event.event_type = 'load' THEN 'in_transit'
                WHEN event.event_type = 'handover' THEN 'issued'
                WHEN event.event_type = 'return' THEN 'returned'
                WHEN event.event_type IN (
                    'receive', 'pack', 'unpack', 'move', 'unload'
                ) THEN 'stored'
                ELSE COALESCE(OLD.state, 'received')
           END
    ) THEN
        RAISE EXCEPTION 'current Logistics state does not match its last event'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.node_id IS NOT NULL AND NEW.current_node_id IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(
            hashtextextended(
                'maru.logistics.containment:' || NEW.organization_id::text,
                0
            )
        );
        IF NOT EXISTS (
            SELECT 1
              FROM public.logistics_logisticsnode AS subject
              JOIN public.logistics_logisticsnode AS destination
                ON destination.id = NEW.current_node_id
             WHERE subject.id = NEW.node_id
               AND subject.organization_id = NEW.organization_id
               AND destination.organization_id = NEW.organization_id
               AND CASE subject.kind
                    WHEN 'storage_site' THEN FALSE
                    WHEN 'storage_area' THEN destination.kind IN ('storage_site', 'venue_room')
                    WHEN 'rack' THEN destination.kind IN ('storage_area', 'container')
                    WHEN 'container' THEN destination.kind IN (
                        'storage_site', 'storage_area', 'vehicle', 'loading_zone',
                        'staging_area', 'venue_room'
                    )
                    WHEN 'box' THEN destination.kind IN (
                        'storage_area', 'rack', 'container', 'box', 'vehicle',
                        'loading_zone', 'staging_area', 'venue_room'
                    )
                    WHEN 'vehicle' THEN destination.kind IN (
                        'storage_site', 'loading_zone', 'staging_area'
                    )
                    WHEN 'loading_zone' THEN destination.kind IN ('storage_site', 'venue_room')
                    WHEN 'staging_area' THEN destination.kind IN (
                        'storage_site', 'loading_zone', 'venue_room'
                    )
                    WHEN 'venue_room' THEN FALSE
                    ELSE FALSE
               END
        ) THEN
            RAISE EXCEPTION 'Logistics node containment type mismatch'
                USING ERRCODE = '23514';
        END IF;
        WITH RECURSIVE ancestors(id, depth) AS (
            SELECT NEW.current_node_id, 1
            UNION ALL
            SELECT state.current_node_id, ancestors.depth + 1
              FROM public.logistics_logisticscurrentstate AS state
              JOIN ancestors ON state.node_id = ancestors.id
             WHERE state.current_node_id IS NOT NULL
               AND ancestors.depth < 128
        )
        SELECT
            bool_or(id = NEW.node_id),
            bool_or(depth >= 128)
          INTO cycle_found, depth_exceeded
          FROM ancestors;
        IF cycle_found OR depth_exceeded THEN
            RAISE EXCEPTION 'Logistics containment graph must remain acyclic and bounded'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_require_logistics_manifest_binding()
RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'logistics_logisticsmanifest' THEN
        IF EXISTS (
            SELECT 1 FROM public.logistics_logisticsmanifest AS current_manifest
             WHERE current_manifest.id = NEW.id
               AND current_manifest.aggregate_version <> NEW.aggregate_version
        ) THEN
            RETURN NULL;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.authorization_scopedresourcebinding AS binding
             WHERE binding.resource_kind = 'logistics.manifest'
               AND binding.resource_id = NEW.id
               AND binding.organization_id = NEW.organization_id
               AND binding.edition_id = NEW.edition_id
               AND binding.department_id = NEW.responsible_department_id
        ) THEN
            RAISE EXCEPTION 'Logistics manifest requires its exact resource binding'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.line_count <> (
            SELECT count(*)
              FROM public.logistics_logisticsmanifestline AS line
             WHERE line.manifest_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'Logistics manifest line count must match immutable evidence'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_logisticsmanifestline' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticsmanifest AS manifest
             WHERE manifest.id = NEW.manifest_id
               AND manifest.line_count = (
                    SELECT count(*)
                      FROM public.logistics_logisticsmanifestline AS line
                     WHERE line.manifest_id = manifest.id
               )
        ) THEN
            RAISE EXCEPTION 'manifest line requires its parent count update'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_reusablekit' THEN
        IF NEW.declared_line_count <> (
            SELECT count(*)
              FROM public.logistics_reusablekitline AS line
             WHERE line.kit_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'reusable kit declared count must match immutable lines'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_reusablekitline' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_reusablekit AS kit
             WHERE kit.id = NEW.kit_id
               AND kit.declared_line_count = (
                    SELECT count(*)
                      FROM public.logistics_reusablekitline AS line
                     WHERE line.kit_id = kit.id
               )
        ) THEN
            RAISE EXCEPTION 'reusable kit line requires exact declared count'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_physicalkey' THEN
        IF EXISTS (
            SELECT 1 FROM public.logistics_physicalkey AS current_key
             WHERE current_key.id = NEW.id
               AND current_key.aggregate_version <> NEW.aggregate_version
        ) THEN
            RETURN NULL;
        END IF;
        IF NEW.aggregate_version <> 1 + (
            SELECT count(*)
              FROM public.logistics_keyholderresponsibility AS responsibility
             WHERE responsibility.key_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'physical-key version must match responsibility evidence'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_keyholderresponsibility' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.logistics_physicalkey AS key
             WHERE key.id = NEW.key_id
               AND key.aggregate_version = 1 + (
                    SELECT count(*)
                      FROM public.logistics_keyholderresponsibility AS responsibility
                     WHERE responsibility.key_id = key.id
               )
        ) THEN
            RAISE EXCEPTION 'keyholder evidence requires its parent version update'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_logisticseditioncontrol' THEN
        IF EXISTS (
            SELECT 1 FROM public.logistics_logisticseditioncontrol AS current_control
             WHERE current_control.id = NEW.id
               AND current_control.aggregate_version <> NEW.aggregate_version
        ) THEN
            RETURN NULL;
        END IF;
        IF NEW.aggregate_version <> (
            SELECT count(*)
              FROM public.logistics_logisticsevent AS event
             WHERE event.organization_id = NEW.organization_id
               AND event.edition_id = NEW.edition_id
        ) THEN
            RAISE EXCEPTION 'edition control version must match Logistics events'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_assetagreement' THEN
        IF NEW.offer_acceptance_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
              FROM public.logistics_equipmentofferacceptance AS acceptance
              JOIN public.logistics_equipmentofferitem AS item
                ON item.id = acceptance.offer_item_id
              JOIN public.logistics_equipmentoffer AS offer
                ON offer.id = item.offer_id
             WHERE acceptance.id = NEW.offer_acceptance_id
               AND offer.status = 'accepted'
               AND NEW.organization_id = offer.organization_id
               AND NEW.edition_id = offer.edition_id
               AND NEW.kind = 'loan'
               AND NEW.aggregate_version = 1
               AND NEW.asset_id IS NOT DISTINCT FROM acceptance.asset_id
               AND NEW.stock_lot_id IS NOT DISTINCT FROM acceptance.stock_lot_id
               AND NEW.physical_key_id IS NULL
               AND NEW.node_id IS NULL
               AND NEW.provider_account_id = offer.offered_by_id
               AND NEW.provider_id IS NULL
               AND NEW.borrower_account_id IS NULL
               AND NEW.borrower_party_id IS NULL
               AND NEW.starts_at = offer.available_from
               AND NEW.ends_at = offer.available_until
               AND NEW.return_due_at = COALESCE(
                    offer.requested_return_at,
                    offer.available_until
               )
               AND NEW.return_address_id IS NULL
               AND NEW.provider_reference = ''
               AND NEW.terms_reference = ''
               AND NEW.created_by_id = offer.reviewed_by_id
        ) THEN
            RAISE EXCEPTION 'offer agreement must match accepted inventory evidence'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_logisticsevent' THEN
        IF NEW.edition_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.logistics_logisticseditioncontrol AS control
             WHERE control.organization_id = NEW.organization_id
               AND control.edition_id = NEW.edition_id
               AND control.aggregate_version = (
                    SELECT count(*)
                      FROM public.logistics_logisticsevent AS event
                     WHERE event.organization_id = control.organization_id
                       AND event.edition_id = control.edition_id
               )
        ) THEN
            RAISE EXCEPTION 'Logistics event requires matching edition control version'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_require_logistics_event_projection()
RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'logistics_offlinescanbatch' THEN
        IF EXISTS (
            SELECT 1
              FROM public.logistics_offlinescanbatch AS current_batch
             WHERE current_batch.id = NEW.id
               AND current_batch.aggregate_version <> NEW.aggregate_version
        ) THEN
            RETURN NULL;
        END IF;
        IF NEW.status = 'pending' OR NEW.aggregate_version <> 2 THEN
            RAISE EXCEPTION 'offline Logistics batch must close before commit'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_logisticsdiscrepancy' THEN
        IF (
            NEW.kind = 'offline_conflict'
            OR EXISTS (
                SELECT 1
                  FROM public.logistics_logisticsevent AS source_event
                 WHERE source_event.id = NEW.detected_event_id
                   AND source_event.source_channel = 'offline'
            )
        ) AND (
            SELECT count(*)
              FROM public.logistics_offlinescanoperation AS operation
             WHERE operation.discrepancy_id = NEW.id
               AND operation.result <> 'duplicate'
        ) <> 1 THEN
            RAISE EXCEPTION 'offline discrepancy requires one canonical operation'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_equipmentoffer' THEN
        IF NOT (
            SELECT count(*) BETWEEN 1 AND 100
              FROM public.logistics_equipmentofferitem AS item
             WHERE item.offer_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'equipment offer requires a bounded item manifest'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM public.logistics_equipmentofferhistory AS history
             WHERE history.offer_id = NEW.id
               AND history.organization_id = NEW.organization_id
               AND history.edition_id = NEW.edition_id
               AND history.status = NEW.status
               AND history.offer_version = NEW.aggregate_version
               AND (
                    (
                        NEW.status IN ('pending', 'withdrawn')
                        AND history.actor_id = NEW.offered_by_id
                    )
                    OR (
                        NEW.status IN ('accepted', 'rejected')
                        AND history.actor_id = NEW.reviewed_by_id
                        AND history.occurred_at = NEW.reviewed_at
                        AND history.reason = NEW.review_reason
                    )
               )
        ) THEN
            RAISE EXCEPTION 'equipment offer version requires matching append-only history'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.logistics_equipmentoffer AS current_offer
             WHERE current_offer.id = NEW.id
               AND current_offer.aggregate_version <> NEW.aggregate_version
        ) THEN
            RETURN NULL;
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM public.logistics_equipmentofferhistory AS history
             WHERE history.offer_id = NEW.id
             GROUP BY history.offer_id
            HAVING count(*) = NEW.aggregate_version
               AND min(history.offer_version) = 1
               AND max(history.offer_version) = NEW.aggregate_version
        ) THEN
            RAISE EXCEPTION 'equipment offer requires contiguous version history'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'accepted' AND EXISTS (
            SELECT 1
              FROM public.logistics_equipmentofferitem AS item
             WHERE item.offer_id = NEW.id
               AND NOT EXISTS (
                    SELECT 1
                      FROM public.logistics_equipmentofferacceptance AS acceptance
                     WHERE acceptance.offer_item_id = item.id
               )
        ) THEN
            RAISE EXCEPTION 'accepted equipment offer requires item acceptance evidence'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status <> 'accepted' AND EXISTS (
            SELECT 1
              FROM public.logistics_equipmentofferitem AS item
              JOIN public.logistics_equipmentofferacceptance AS acceptance
                ON acceptance.offer_item_id = item.id
             WHERE item.offer_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'non-accepted equipment offer cannot retain acceptance evidence'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_equipmentofferhistory' THEN
        IF NEW.offer_version = 1 AND NOT EXISTS (
            SELECT 1 FROM public.logistics_equipmentoffer AS offer
             WHERE offer.id = NEW.offer_id
               AND offer.organization_id = NEW.organization_id
               AND offer.edition_id = NEW.edition_id
               AND NEW.status = 'pending'
               AND NEW.actor_id = offer.offered_by_id
               AND offer.aggregate_version IN (1, 2)
        ) THEN
            RAISE EXCEPTION 'initial equipment-offer history is invalid'
                USING ERRCODE = '23514';
        ELSIF NEW.offer_version = 2 AND NOT EXISTS (
            SELECT 1 FROM public.logistics_equipmentoffer AS offer
             WHERE offer.id = NEW.offer_id
               AND offer.organization_id = NEW.organization_id
               AND offer.edition_id = NEW.edition_id
               AND offer.aggregate_version = 2
               AND offer.status = NEW.status
               AND (
                    (
                        NEW.status = 'withdrawn'
                        AND NEW.actor_id = offer.offered_by_id
                    )
                    OR (
                        NEW.status IN ('accepted', 'rejected')
                        AND NEW.actor_id = offer.reviewed_by_id
                        AND NEW.occurred_at = offer.reviewed_at
                        AND NEW.reason = offer.review_reason
                    )
               )
        ) THEN
            RAISE EXCEPTION 'terminal equipment-offer history is invalid'
                USING ERRCODE = '23514';
        ELSIF NEW.offer_version NOT IN (1, 2) THEN
            RAISE EXCEPTION 'equipment offer history must match its final offer version'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_equipmentofferacceptance' THEN
        IF NOT EXISTS (
            SELECT 1
              FROM public.logistics_equipmentofferitem AS item
              JOIN public.logistics_equipmentoffer AS offer ON offer.id = item.offer_id
              LEFT JOIN public.logistics_asset AS asset ON asset.id = NEW.asset_id
              LEFT JOIN public.logistics_stocklot AS lot ON lot.id = NEW.stock_lot_id
              JOIN public.logistics_assetagreement AS agreement
                ON agreement.offer_acceptance_id = NEW.id
             WHERE item.id = NEW.offer_item_id
               AND offer.status = 'accepted'
               AND NEW.accepted_by_id = offer.reviewed_by_id
               AND NEW.accepted_at = offer.reviewed_at
               AND (
                    (
                        item.kind = 'serialized'
                        AND NEW.asset_id IS NOT NULL
                        AND NEW.stock_lot_id IS NULL
                        AND asset.organization_id = offer.organization_id
                        AND asset.edition_allocation_id = offer.edition_id
                        AND asset.catalog_code = 'offer-' || replace(item.id::text, '-', '')
                        AND asset.name = item.name
                        AND asset.asset_type = 'offered_equipment'
                        AND asset.manufacturer = item.manufacturer
                        AND asset.model_name = item.model_name
                        AND asset.serial_number = item.serial_number
                        AND asset.acquisition = 'equipment_offer'
                        AND asset.value_class = item.value_class
                        AND asset.maintenance_due_at IS NULL
                        AND asset.owner_kind = 'account'
                        AND asset.owner_account_id = offer.offered_by_id
                        AND asset.owner_party_id IS NULL
                        AND asset.lifecycle = 'active'
                        AND asset.aggregate_version = 1
                        AND asset.created_by_id = offer.reviewed_by_id
                    )
                    OR (
                        item.kind = 'bulk'
                        AND NEW.asset_id IS NULL
                        AND NEW.stock_lot_id IS NOT NULL
                        AND lot.organization_id = offer.organization_id
                        AND lot.edition_allocation_id = offer.edition_id
                        AND lot.catalog_code = 'offer-' || replace(item.id::text, '-', '')
                        AND lot.name = item.name
                        AND lot.stock_type = 'offered_stock'
                        AND lot.unit = 'item'
                        AND lot.initial_quantity = item.quantity
                        AND lot.value_class = item.value_class
                        AND lot.owner_kind = 'account'
                        AND lot.owner_account_id = offer.offered_by_id
                        AND lot.owner_party_id IS NULL
                        AND lot.lifecycle = 'active'
                        AND lot.aggregate_version = 1
                        AND lot.created_by_id = offer.reviewed_by_id
                    )
               )
               AND agreement.organization_id = offer.organization_id
               AND agreement.edition_id = offer.edition_id
               AND agreement.kind = 'loan'
               AND agreement.asset_id IS NOT DISTINCT FROM NEW.asset_id
               AND agreement.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
               AND agreement.physical_key_id IS NULL
               AND agreement.node_id IS NULL
               AND agreement.provider_account_id = offer.offered_by_id
               AND agreement.provider_id IS NULL
               AND agreement.borrower_account_id IS NULL
               AND agreement.borrower_party_id IS NULL
               AND agreement.starts_at = offer.available_from
               AND agreement.ends_at = offer.available_until
               AND agreement.return_due_at = COALESCE(
                    offer.requested_return_at,
                    offer.available_until
               )
               AND agreement.return_address_id IS NULL
               AND agreement.provider_reference = ''
               AND agreement.terms_reference = ''
               AND agreement.aggregate_version = 1
               AND agreement.created_by_id = offer.reviewed_by_id
        ) THEN
            RAISE EXCEPTION 'equipment offer acceptance requires canonical inventory and agreement evidence'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_asset' THEN
        IF NEW.acquisition = 'equipment_offer'
           OR NEW.catalog_code ~ '^offer-[0-9a-f]{32}$'
        THEN
            IF NEW.acquisition <> 'equipment_offer'
               OR NEW.catalog_code !~ '^offer-[0-9a-f]{32}$'
            THEN
                RAISE EXCEPTION 'offer-derived asset requires canonical identity'
                    USING ERRCODE = '23514';
            END IF;
            IF NOT EXISTS (
                    SELECT 1
                      FROM public.logistics_equipmentofferitem AS item
                      JOIN public.logistics_equipmentoffer AS offer
                        ON offer.id = item.offer_id
                      JOIN public.logistics_equipmentofferacceptance AS acceptance
                        ON acceptance.offer_item_id = item.id
                       AND acceptance.asset_id = NEW.id
                     WHERE item.id = substring(NEW.catalog_code FROM 7)::uuid
                       AND item.kind = 'serialized'
                       AND offer.status = 'accepted'
            ) THEN
                RAISE EXCEPTION 'offer-derived asset requires final acceptance evidence'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_stocklot' THEN
        IF NEW.stock_type = 'offered_stock'
           OR NEW.catalog_code ~ '^offer-[0-9a-f]{32}$'
        THEN
            IF NEW.stock_type <> 'offered_stock'
               OR NEW.catalog_code !~ '^offer-[0-9a-f]{32}$'
            THEN
                RAISE EXCEPTION 'offer-derived stock requires canonical identity'
                    USING ERRCODE = '23514';
            END IF;
            IF NOT EXISTS (
                    SELECT 1
                      FROM public.logistics_equipmentofferitem AS item
                      JOIN public.logistics_equipmentoffer AS offer
                        ON offer.id = item.offer_id
                      JOIN public.logistics_equipmentofferacceptance AS acceptance
                        ON acceptance.offer_item_id = item.id
                       AND acceptance.stock_lot_id = NEW.id
                     WHERE item.id = substring(NEW.catalog_code FROM 7)::uuid
                       AND item.kind = 'bulk'
                       AND offer.status = 'accepted'
            ) THEN
                RAISE EXCEPTION 'offer-derived stock requires final acceptance evidence'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_offlinescanoperation' THEN
        IF NEW.result = 'duplicate' THEN
            IF NEW.reason_code <> 'logistics_offline_duplicate' OR NOT EXISTS (
                SELECT 1
                  FROM public.logistics_offlineoperationreceipt AS receipt
                  JOIN public.logistics_offlinescanbatch AS batch
                    ON batch.id = NEW.batch_id
                  JOIN public.logistics_offlinescanoperation AS prior_operation
                    ON prior_operation.idempotency_key = receipt.idempotency_key
                   AND prior_operation.result <> 'duplicate'
                   AND NOT (
                        prior_operation.result = 'review'
                        AND prior_operation.reason_code =
                            'logistics_offline_idempotency_conflict'
                   )
                 WHERE receipt.idempotency_key = NEW.idempotency_key
                   AND receipt.organization_id = batch.organization_id
                   AND receipt.edition_id = batch.edition_id
                   AND receipt.operation_digest = NEW.operation_digest
                   AND receipt.applied_event_id IS NOT DISTINCT FROM NEW.applied_event_id
                   AND receipt.discrepancy_id IS NOT DISTINCT FROM NEW.discrepancy_id
                   AND receipt.result IN ('applied', 'review')
                   AND prior_operation.operation_digest = receipt.operation_digest
                   AND prior_operation.result = receipt.result
                   AND prior_operation.reason_code = receipt.reason_code
                   AND prior_operation.applied_event_id IS NOT DISTINCT FROM
                        receipt.applied_event_id
                   AND prior_operation.discrepancy_id IS NOT DISTINCT FROM
                        receipt.discrepancy_id
                   AND prior_operation.sequence = NEW.sequence
                   AND prior_operation.expected_subject_sequence =
                        NEW.expected_subject_sequence
                   AND prior_operation.action = NEW.action
                   AND prior_operation.label_code = NEW.label_code
                   AND prior_operation.source_label_code = NEW.source_label_code
                   AND prior_operation.destination_label_code =
                        NEW.destination_label_code
                   AND prior_operation.quantity IS NOT DISTINCT FROM NEW.quantity
                   AND prior_operation.observed_condition = NEW.observed_condition
                   AND prior_operation.occurred_at = NEW.occurred_at
            ) THEN
                RAISE EXCEPTION 'duplicate offline operation must reuse exact receipt evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.result = 'review'
              AND NEW.reason_code = 'logistics_offline_idempotency_conflict'
        THEN
            IF NEW.applied_event_id IS NOT NULL OR NOT EXISTS (
                SELECT 1
                  FROM public.logistics_offlineoperationreceipt AS receipt
                  JOIN public.logistics_offlinescanbatch AS batch
                    ON batch.id = NEW.batch_id
                  JOIN public.logistics_logisticsdiscrepancy AS discrepancy
                    ON discrepancy.id = NEW.discrepancy_id
                 WHERE receipt.idempotency_key = NEW.idempotency_key
                   AND (
                        receipt.organization_id <> batch.organization_id
                        OR receipt.edition_id <> batch.edition_id
                        OR receipt.operation_digest <> NEW.operation_digest
                   )
                   AND discrepancy.organization_id = batch.organization_id
                   AND discrepancy.edition_id = batch.edition_id
                   AND discrepancy.kind = 'offline_conflict'
                   AND discrepancy.status = 'open'
                   AND discrepancy.aggregate_version = 1
                   AND discrepancy.detected_event_id IS NULL
                   AND discrepancy.expected_quantity IS NULL
                   AND discrepancy.observed_quantity IS NULL
                   AND discrepancy.description =
                        'Offline idempotency evidence conflicts with prior use.'
                   AND (
                        EXISTS (
                            SELECT 1
                              FROM public.logistics_logisticslabel AS label
                             WHERE label.organization_id = batch.organization_id
                               AND label.label_code = NEW.label_code
                               AND label.lifecycle = 'active'
                               AND (
                                    (label.node_id IS NOT NULL
                                     AND discrepancy.subject_kind = 'node'
                                     AND discrepancy.subject_id = label.node_id)
                                    OR (label.asset_id IS NOT NULL
                                        AND discrepancy.subject_kind = 'asset'
                                        AND discrepancy.subject_id = label.asset_id)
                                    OR (label.stock_lot_id IS NOT NULL
                                        AND discrepancy.subject_kind = 'stock_lot'
                                        AND discrepancy.subject_id = label.stock_lot_id)
                                    OR (label.physical_key_id IS NOT NULL
                                        AND discrepancy.subject_kind = 'key'
                                        AND discrepancy.subject_id = label.physical_key_id)
                               )
                        )
                        OR (
                            NOT EXISTS (
                                SELECT 1
                                  FROM public.logistics_logisticslabel AS label
                                 WHERE label.organization_id = batch.organization_id
                                   AND label.label_code = NEW.label_code
                                   AND label.lifecycle = 'active'
                            )
                            AND discrepancy.subject_kind = 'node'
                            AND discrepancy.subject_id = batch.id
                        )
                   )
            ) THEN
                RAISE EXCEPTION 'offline idempotency conflict requires exact discrepancy evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.result = 'applied' THEN
            IF NOT EXISTS (
                SELECT 1
                  FROM public.logistics_offlineoperationreceipt AS receipt
                  JOIN public.logistics_offlinescanbatch AS batch
                    ON batch.id = NEW.batch_id
                  JOIN public.logistics_logisticsevent AS event
                    ON event.id = NEW.applied_event_id
                  JOIN public.logistics_logisticslabel AS subject_label
                    ON subject_label.organization_id = batch.organization_id
                   AND subject_label.label_code = NEW.label_code
                   AND subject_label.lifecycle = 'active'
                 WHERE receipt.idempotency_key = NEW.idempotency_key
                   AND receipt.organization_id = batch.organization_id
                   AND receipt.edition_id = batch.edition_id
                   AND receipt.operation_digest = NEW.operation_digest
                   AND receipt.result = 'applied'
                   AND receipt.reason_code = 'logistics_offline_applied'
                   AND receipt.applied_event_id IS NOT DISTINCT FROM NEW.applied_event_id
                   AND receipt.discrepancy_id IS NOT DISTINCT FROM NEW.discrepancy_id
                   AND NEW.reason_code = 'logistics_offline_applied'
                   AND event.organization_id = batch.organization_id
                   AND event.edition_id = batch.edition_id
                   AND event.actor_id = batch.submitted_by_id
                   AND event.event_type = NEW.action
                   AND NEW.action <> 'handover'
                   AND event.event_sequence = NEW.expected_subject_sequence + 1
                   AND event.occurred_at = NEW.occurred_at
                   AND event.quantity IS NOT DISTINCT FROM NEW.quantity
                   AND event.source_channel = 'offline'
                   AND event.manifest_id IS NULL
                   AND event.evidence_reference = ''
                   AND (
                        (
                            event.event_type = 'receive'
                            AND event.from_custodian_account_id IS NULL
                            AND event.to_custodian_account_id IS NULL
                            AND event.from_custodian_party_id IS NULL
                            AND event.to_custodian_party_id IS NULL
                        )
                        OR (
                            event.event_type NOT IN ('receive', 'handover', 'return')
                            AND event.to_custodian_account_id IS NOT DISTINCT FROM
                                event.from_custodian_account_id
                            AND event.to_custodian_party_id IS NOT DISTINCT FROM
                                event.from_custodian_party_id
                        )
                        OR (
                            event.event_type = 'return'
                            AND event.to_custodian_account_id IS NULL
                            AND event.to_custodian_party_id IS NULL
                        )
                   )
                   AND (
                        (subject_label.node_id IS NOT NULL
                         AND event.subject_kind = 'node'
                         AND event.node_id = subject_label.node_id)
                        OR (subject_label.asset_id IS NOT NULL
                            AND event.subject_kind = 'asset'
                            AND event.asset_id = subject_label.asset_id)
                        OR (subject_label.stock_lot_id IS NOT NULL
                            AND event.subject_kind = 'stock_lot'
                            AND event.stock_lot_id = subject_label.stock_lot_id)
                        OR (subject_label.physical_key_id IS NOT NULL
                            AND event.subject_kind = 'key'
                            AND event.physical_key_id = subject_label.physical_key_id)
                   )
                   AND (
                        NEW.source_label_code = ''
                        OR EXISTS (
                            SELECT 1
                              FROM public.logistics_logisticslabel AS source_label
                             WHERE source_label.organization_id = batch.organization_id
                               AND source_label.label_code = NEW.source_label_code
                               AND source_label.lifecycle = 'active'
                               AND source_label.node_id = event.source_node_id
                        )
                   )
                   AND (
                        (NEW.destination_label_code = ''
                         AND event.destination_node_id IS NULL)
                        OR EXISTS (
                            SELECT 1
                              FROM public.logistics_logisticslabel AS destination_label
                             WHERE destination_label.organization_id = batch.organization_id
                               AND destination_label.label_code = NEW.destination_label_code
                               AND destination_label.lifecycle = 'active'
                               AND destination_label.node_id = event.destination_node_id
                        )
                   )
                   AND (
                        (NEW.observed_condition <> ''
                         AND event.condition_after = NEW.observed_condition)
                        OR (NEW.observed_condition = ''
                            AND event.condition_after = event.condition_before)
                   )
                   AND (
                        (
                            NEW.discrepancy_id IS NULL
                            AND NOT EXISTS (
                                SELECT 1
                                  FROM public.logistics_logisticsdiscrepancy AS discrepancy
                                 WHERE discrepancy.detected_event_id = event.id
                            )
                        )
                        OR EXISTS (
                            SELECT 1
                              FROM public.logistics_logisticsdiscrepancy AS discrepancy
                             WHERE discrepancy.id = NEW.discrepancy_id
                               AND discrepancy.detected_event_id = event.id
                               AND discrepancy.organization_id = batch.organization_id
                               AND discrepancy.edition_id = batch.edition_id
                               AND discrepancy.kind IN ('count', 'damage')
                               AND discrepancy.status = 'open'
                               AND discrepancy.aggregate_version = 1
                        )
                   )
            ) OR EXISTS (
                SELECT 1
                  FROM public.logistics_offlinescanoperation AS other_operation
                 WHERE other_operation.id <> NEW.id
                   AND other_operation.idempotency_key = NEW.idempotency_key
                   AND other_operation.result <> 'duplicate'
                   AND NOT (
                        other_operation.result = 'review'
                        AND other_operation.reason_code = 'logistics_offline_idempotency_conflict'
                   )
            ) THEN
                RAISE EXCEPTION 'applied offline operation requires exact event and receipt evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.result = 'review'
              AND NEW.reason_code IN (
                    'logistics_offline_state_conflict',
                    'logistics_offline_label_unavailable'
              )
        THEN
            IF NEW.applied_event_id IS NOT NULL OR NOT EXISTS (
                SELECT 1
                  FROM public.logistics_offlineoperationreceipt AS receipt
                  JOIN public.logistics_offlinescanbatch AS batch
                    ON batch.id = NEW.batch_id
                  JOIN public.logistics_logisticsdiscrepancy AS discrepancy
                    ON discrepancy.id = NEW.discrepancy_id
                 WHERE receipt.idempotency_key = NEW.idempotency_key
                   AND receipt.organization_id = batch.organization_id
                   AND receipt.edition_id = batch.edition_id
                   AND receipt.operation_digest = NEW.operation_digest
                   AND receipt.result = 'review'
                   AND receipt.reason_code = NEW.reason_code
                   AND receipt.applied_event_id IS NULL
                   AND receipt.discrepancy_id = NEW.discrepancy_id
                   AND discrepancy.organization_id = batch.organization_id
                   AND discrepancy.edition_id = batch.edition_id
                   AND discrepancy.kind = 'offline_conflict'
                   AND discrepancy.status = 'open'
                   AND discrepancy.aggregate_version = 1
                   AND discrepancy.detected_event_id IS NULL
                   AND discrepancy.expected_quantity IS NULL
                   AND discrepancy.observed_quantity IS NULL
                   AND discrepancy.description = CASE NEW.reason_code
                        WHEN 'logistics_offline_state_conflict' THEN
                            'Offline scan conflicts with the current subject projection.'
                        ELSE 'Offline scan contains an unknown or invalid label.'
                   END
                   AND (
                        (
                            NEW.reason_code = 'logistics_offline_state_conflict'
                            AND EXISTS (
                                SELECT 1
                                  FROM public.logistics_logisticslabel AS label
                                 WHERE label.organization_id = batch.organization_id
                                   AND label.label_code = NEW.label_code
                                   AND label.lifecycle = 'active'
                            )
                            AND (
                                NEW.source_label_code = ''
                                OR EXISTS (
                                    SELECT 1
                                      FROM public.logistics_logisticslabel AS source_label
                                     WHERE source_label.organization_id = batch.organization_id
                                       AND source_label.label_code = NEW.source_label_code
                                       AND source_label.lifecycle = 'active'
                                       AND source_label.node_id IS NOT NULL
                                )
                            )
                            AND (
                                NEW.destination_label_code = ''
                                OR EXISTS (
                                    SELECT 1
                                      FROM public.logistics_logisticslabel AS destination_label
                                     WHERE destination_label.organization_id = batch.organization_id
                                       AND destination_label.label_code = NEW.destination_label_code
                                       AND destination_label.lifecycle = 'active'
                                       AND destination_label.node_id IS NOT NULL
                                )
                            )
                        )
                        OR (
                            NEW.reason_code = 'logistics_offline_label_unavailable'
                            AND NOT (
                                EXISTS (
                                    SELECT 1
                                      FROM public.logistics_logisticslabel AS label
                                     WHERE label.organization_id = batch.organization_id
                                       AND label.label_code = NEW.label_code
                                       AND label.lifecycle = 'active'
                                )
                                AND (
                                    NEW.source_label_code = ''
                                    OR EXISTS (
                                        SELECT 1
                                          FROM public.logistics_logisticslabel AS source_label
                                         WHERE source_label.organization_id = batch.organization_id
                                           AND source_label.label_code = NEW.source_label_code
                                           AND source_label.lifecycle = 'active'
                                           AND source_label.node_id IS NOT NULL
                                    )
                                )
                                AND (
                                    NEW.destination_label_code = ''
                                    OR EXISTS (
                                        SELECT 1
                                          FROM public.logistics_logisticslabel AS destination_label
                                         WHERE destination_label.organization_id = batch.organization_id
                                           AND destination_label.label_code = NEW.destination_label_code
                                           AND destination_label.lifecycle = 'active'
                                           AND destination_label.node_id IS NOT NULL
                                    )
                                )
                            )
                        )
                   )
                   AND (
                        EXISTS (
                            SELECT 1
                              FROM public.logistics_logisticslabel AS label
                             WHERE label.organization_id = batch.organization_id
                               AND label.label_code = NEW.label_code
                               AND label.lifecycle = 'active'
                               AND (
                                    (label.node_id IS NOT NULL
                                     AND discrepancy.subject_kind = 'node'
                                     AND discrepancy.subject_id = label.node_id)
                                    OR (label.asset_id IS NOT NULL
                                        AND discrepancy.subject_kind = 'asset'
                                        AND discrepancy.subject_id = label.asset_id)
                                    OR (label.stock_lot_id IS NOT NULL
                                        AND discrepancy.subject_kind = 'stock_lot'
                                        AND discrepancy.subject_id = label.stock_lot_id)
                                    OR (label.physical_key_id IS NOT NULL
                                        AND discrepancy.subject_kind = 'key'
                                        AND discrepancy.subject_id = label.physical_key_id)
                               )
                        )
                        OR (
                            NEW.reason_code = 'logistics_offline_label_unavailable'
                            AND NOT EXISTS (
                                SELECT 1
                                  FROM public.logistics_logisticslabel AS label
                                 WHERE label.organization_id = batch.organization_id
                                   AND label.label_code = NEW.label_code
                                   AND label.lifecycle = 'active'
                            )
                            AND discrepancy.subject_kind = 'node'
                            AND discrepancy.subject_id = batch.id
                        )
                   )
            ) OR EXISTS (
                SELECT 1
                  FROM public.logistics_offlinescanoperation AS other_operation
                 WHERE other_operation.id <> NEW.id
                   AND other_operation.idempotency_key = NEW.idempotency_key
                   AND other_operation.result <> 'duplicate'
                   AND NOT (
                        other_operation.result = 'review'
                        AND other_operation.reason_code = 'logistics_offline_idempotency_conflict'
                   )
            ) THEN
                RAISE EXCEPTION 'review offline operation requires exact discrepancy and receipt evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'offline operation result is not produced by reconciliation'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME = 'logistics_offlineoperationreceipt' THEN
        IF NEW.result NOT IN ('applied', 'review') OR NOT EXISTS (
            SELECT 1
              FROM public.logistics_offlinescanoperation AS operation
              JOIN public.logistics_offlinescanbatch AS batch
                ON batch.id = operation.batch_id
             WHERE operation.idempotency_key = NEW.idempotency_key
               AND operation.result <> 'duplicate'
               AND NOT (
                    operation.result = 'review'
                    AND operation.reason_code = 'logistics_offline_idempotency_conflict'
               )
               AND batch.organization_id = NEW.organization_id
               AND batch.edition_id = NEW.edition_id
               AND operation.operation_digest = NEW.operation_digest
               AND operation.result = NEW.result
               AND operation.reason_code = NEW.reason_code
               AND operation.applied_event_id IS NOT DISTINCT FROM NEW.applied_event_id
               AND operation.discrepancy_id IS NOT DISTINCT FROM NEW.discrepancy_id
        ) THEN
            RAISE EXCEPTION 'offline receipt requires its canonical operation'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF NEW.source_channel = 'offline' AND (
        SELECT count(*)
          FROM public.logistics_offlinescanoperation AS operation
         WHERE operation.applied_event_id = NEW.id
           AND operation.result <> 'duplicate'
    ) <> 1 THEN
        RAISE EXCEPTION 'offline event requires one canonical operation'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.logistics_logisticsevent AS successor
         WHERE successor.organization_id = NEW.organization_id
           AND successor.node_id IS NOT DISTINCT FROM NEW.node_id
           AND successor.asset_id IS NOT DISTINCT FROM NEW.asset_id
           AND successor.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
           AND successor.physical_key_id IS NOT DISTINCT FROM NEW.physical_key_id
           AND successor.event_sequence > NEW.event_sequence
    ) AND NOT EXISTS (
        SELECT 1 FROM public.logistics_logisticscurrentstate AS state
         WHERE state.organization_id = NEW.organization_id
           AND state.node_id IS NOT DISTINCT FROM NEW.node_id
           AND state.asset_id IS NOT DISTINCT FROM NEW.asset_id
           AND state.stock_lot_id IS NOT DISTINCT FROM NEW.stock_lot_id
           AND state.physical_key_id IS NOT DISTINCT FROM NEW.physical_key_id
           AND state.event_sequence = NEW.event_sequence
           AND state.last_event_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'Logistics event requires its resulting current-state projection'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.event_type = 'count' AND EXISTS (
        SELECT 1 FROM public.logistics_logisticsevent AS prior
         WHERE prior.stock_lot_id = NEW.stock_lot_id
           AND prior.event_sequence = NEW.event_sequence - 1
           AND prior.quantity IS DISTINCT FROM NEW.quantity
    ) AND NOT EXISTS (
        SELECT 1 FROM public.logistics_logisticsdiscrepancy AS discrepancy
         WHERE discrepancy.detected_event_id = NEW.id
           AND discrepancy.organization_id = NEW.organization_id
           AND discrepancy.edition_id IS NOT DISTINCT FROM NEW.edition_id
           AND discrepancy.kind = 'count'
           AND discrepancy.subject_kind = NEW.subject_kind
           AND discrepancy.subject_id = NEW.stock_lot_id
           AND discrepancy.expected_quantity IS NOT DISTINCT FROM (
                SELECT prior.quantity
                  FROM public.logistics_logisticsevent AS prior
                 WHERE prior.stock_lot_id = NEW.stock_lot_id
                   AND prior.event_sequence = NEW.event_sequence - 1
           )
           AND discrepancy.observed_quantity IS NOT DISTINCT FROM NEW.quantity
    ) THEN
        RAISE EXCEPTION 'changed Logistics count requires discrepancy evidence'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.event_type = 'damage' AND NOT EXISTS (
        SELECT 1 FROM public.logistics_logisticsdiscrepancy AS discrepancy
         WHERE discrepancy.detected_event_id = NEW.id
           AND discrepancy.organization_id = NEW.organization_id
           AND discrepancy.edition_id IS NOT DISTINCT FROM NEW.edition_id
           AND discrepancy.kind = 'damage'
           AND discrepancy.subject_kind = NEW.subject_kind
           AND discrepancy.subject_id = CASE NEW.subject_kind
                WHEN 'node' THEN NEW.node_id
                WHEN 'asset' THEN NEW.asset_id
                WHEN 'stock_lot' THEN NEW.stock_lot_id
                WHEN 'key' THEN NEW.physical_key_id
           END
    ) THEN
        RAISE EXCEPTION 'Logistics damage requires discrepancy evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
"""

CATALOG_SCOPE_TABLES = (
    "logistics_equipmentoffer",
    "logistics_equipmentofferitem",
    "logistics_equipmentofferhistory",
    "logistics_equipmentofferacceptance",
    "logistics_logisticsnode",
    "logistics_asset",
    "logistics_stocklot",
    "logistics_physicalkey",
    "logistics_keyholderresponsibility",
    "logistics_assetagreement",
    "logistics_reusablekitline",
    "logistics_logisticsmanifest",
    "logistics_logisticsmanifestline",
    "logistics_logisticslabel",
)

EVIDENCE_SCOPE_TABLES = (
    "logistics_logisticsevent",
    "logistics_logisticsdiscrepancy",
    "logistics_logisticseditioncontrol",
    "logistics_offlinescanbatch",
    "logistics_offlinescanoperation",
    "logistics_offlineoperationreceipt",
    "logistics_logisticscommandreceipt",
)


def _trigger_stem(table: str) -> str:
    return table.removeprefix("logistics_")


def _install_trigger_sql() -> str:
    statements: list[str] = []
    for table in APPEND_ONLY_TABLES:
        statements.append(
            f"""
CREATE TRIGGER log_{_trigger_stem(table)}_append_only
BEFORE UPDATE OR DELETE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_logistics_evidence_mutation();
"""
        )
    for table in ENTITY_TABLES:
        statements.append(
            f"""
CREATE TRIGGER log_{_trigger_stem(table)}_identity_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_logistics_entity_identity();
"""
        )
    for table in TRUNCATE_TABLES:
        statements.append(
            f"""
CREATE TRIGGER log_{_trigger_stem(table)}_no_truncate
BEFORE TRUNCATE ON public.{table}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_logistics_evidence_mutation();
"""
        )
    for table in CATALOG_SCOPE_TABLES:
        statements.append(
            f"""
CREATE TRIGGER log_{_trigger_stem(table)}_catalog_scope
BEFORE INSERT OR UPDATE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_logistics_catalog_scope();
"""
        )
    for table in EVIDENCE_SCOPE_TABLES:
        statements.append(
            f"""
CREATE TRIGGER log_{_trigger_stem(table)}_evidence_scope
BEFORE INSERT OR UPDATE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_logistics_evidence_scope();
"""
        )
    statements.append(
        r"""
CREATE TRIGGER log_restricted_address_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.logistics_restrictedlogisticsaddress
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_logistics_restricted_address();

CREATE TRIGGER log_current_state_correspondence
BEFORE INSERT OR UPDATE OR DELETE
ON public.logistics_logisticscurrentstate
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_logistics_current_state();

CREATE CONSTRAINT TRIGGER log_manifest_binding_required
AFTER INSERT OR UPDATE ON public.logistics_logisticsmanifest
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_manifest_line_count_required
AFTER INSERT ON public.logistics_logisticsmanifestline
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_kit_line_count_required
AFTER INSERT ON public.logistics_reusablekit
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_kit_line_parent_required
AFTER INSERT ON public.logistics_reusablekitline
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_physical_key_evidence_required
AFTER INSERT OR UPDATE ON public.logistics_physicalkey
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_keyholder_parent_required
AFTER INSERT ON public.logistics_keyholderresponsibility
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_edition_control_evidence_required
AFTER INSERT OR UPDATE ON public.logistics_logisticseditioncontrol
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_event_edition_control_required
AFTER INSERT ON public.logistics_logisticsevent
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_offer_agreement_correspondence
AFTER INSERT ON public.logistics_assetagreement
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_manifest_binding();

CREATE CONSTRAINT TRIGGER log_event_projection_required
AFTER INSERT ON public.logistics_logisticsevent
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offer_history_required
AFTER INSERT OR UPDATE ON public.logistics_equipmentoffer
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offer_history_correspondence
AFTER INSERT ON public.logistics_equipmentofferhistory
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offer_acceptance_correspondence
AFTER INSERT ON public.logistics_equipmentofferacceptance
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offer_asset_correspondence
AFTER INSERT ON public.logistics_asset
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offer_stock_correspondence
AFTER INSERT ON public.logistics_stocklot
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offline_operation_correspondence
AFTER INSERT ON public.logistics_offlinescanoperation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offline_receipt_correspondence
AFTER INSERT ON public.logistics_offlineoperationreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offline_batch_closure_required
AFTER INSERT OR UPDATE ON public.logistics_offlinescanbatch
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

CREATE CONSTRAINT TRIGGER log_offline_discrepancy_correspondence
AFTER INSERT ON public.logistics_logisticsdiscrepancy
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_logistics_event_projection();

REVOKE ALL ON FUNCTION
    public.maru_prevent_logistics_evidence_mutation(),
    public.maru_guard_logistics_entity_identity(),
    public.maru_logistics_person_is_eligible(uuid, uuid, uuid, uuid),
    public.maru_guard_logistics_restricted_address(),
    public.maru_validate_logistics_catalog_scope(),
    public.maru_validate_logistics_evidence_scope(),
    public.maru_guard_logistics_current_state(),
    public.maru_require_logistics_manifest_binding(),
    public.maru_require_logistics_event_projection()
FROM PUBLIC;
"""
    )
    return "\n".join(statements)


def _remove_trigger_sql() -> str:
    statements: list[str] = [
        "DROP TRIGGER IF EXISTS log_offline_discrepancy_correspondence "
        "ON public.logistics_logisticsdiscrepancy;",
        "DROP TRIGGER IF EXISTS log_offline_batch_closure_required "
        "ON public.logistics_offlinescanbatch;",
        "DROP TRIGGER IF EXISTS log_offline_receipt_correspondence "
        "ON public.logistics_offlineoperationreceipt;",
        "DROP TRIGGER IF EXISTS log_offline_operation_correspondence "
        "ON public.logistics_offlinescanoperation;",
        "DROP TRIGGER IF EXISTS log_offer_agreement_correspondence "
        "ON public.logistics_assetagreement;",
        "DROP TRIGGER IF EXISTS log_event_edition_control_required "
        "ON public.logistics_logisticsevent;",
        "DROP TRIGGER IF EXISTS log_edition_control_evidence_required "
        "ON public.logistics_logisticseditioncontrol;",
        "DROP TRIGGER IF EXISTS log_keyholder_parent_required "
        "ON public.logistics_keyholderresponsibility;",
        "DROP TRIGGER IF EXISTS log_physical_key_evidence_required "
        "ON public.logistics_physicalkey;",
        "DROP TRIGGER IF EXISTS log_kit_line_parent_required "
        "ON public.logistics_reusablekitline;",
        "DROP TRIGGER IF EXISTS log_kit_line_count_required "
        "ON public.logistics_reusablekit;",
        "DROP TRIGGER IF EXISTS log_manifest_line_count_required "
        "ON public.logistics_logisticsmanifestline;",
        "DROP TRIGGER IF EXISTS log_offer_acceptance_correspondence "
        "ON public.logistics_equipmentofferacceptance;",
        "DROP TRIGGER IF EXISTS log_offer_asset_correspondence "
        "ON public.logistics_asset;",
        "DROP TRIGGER IF EXISTS log_offer_stock_correspondence "
        "ON public.logistics_stocklot;",
        "DROP TRIGGER IF EXISTS log_offer_history_correspondence "
        "ON public.logistics_equipmentofferhistory;",
        "DROP TRIGGER IF EXISTS log_offer_history_required "
        "ON public.logistics_equipmentoffer;",
        "DROP TRIGGER IF EXISTS log_event_projection_required "
        "ON public.logistics_logisticsevent;",
        "DROP TRIGGER IF EXISTS log_manifest_binding_required "
        "ON public.logistics_logisticsmanifest;",
        "DROP TRIGGER IF EXISTS log_current_state_correspondence "
        "ON public.logistics_logisticscurrentstate;",
        "DROP TRIGGER IF EXISTS log_restricted_address_guard "
        "ON public.logistics_restrictedlogisticsaddress;",
    ]
    for table in reversed(EVIDENCE_SCOPE_TABLES):
        statements.append(
            f"DROP TRIGGER IF EXISTS log_{_trigger_stem(table)}_evidence_scope "
            f"ON public.{table};"
        )
    for table in reversed(CATALOG_SCOPE_TABLES):
        statements.append(
            f"DROP TRIGGER IF EXISTS log_{_trigger_stem(table)}_catalog_scope "
            f"ON public.{table};"
        )
    for table in reversed(TRUNCATE_TABLES):
        statements.append(
            f"DROP TRIGGER IF EXISTS log_{_trigger_stem(table)}_no_truncate "
            f"ON public.{table};"
        )
    for table in reversed(ENTITY_TABLES):
        statements.append(
            f"DROP TRIGGER IF EXISTS log_{_trigger_stem(table)}_identity_guard "
            f"ON public.{table};"
        )
    for table in reversed(APPEND_ONLY_TABLES):
        statements.append(
            f"DROP TRIGGER IF EXISTS log_{_trigger_stem(table)}_append_only "
            f"ON public.{table};"
        )
    statements.extend(
        (
            "DROP FUNCTION IF EXISTS public.maru_require_logistics_event_projection();",
            "DROP FUNCTION IF EXISTS public.maru_require_logistics_manifest_binding();",
            "DROP FUNCTION IF EXISTS public.maru_guard_logistics_current_state();",
            "DROP FUNCTION IF EXISTS public.maru_validate_logistics_evidence_scope();",
            "DROP FUNCTION IF EXISTS public.maru_validate_logistics_catalog_scope();",
            "DROP FUNCTION IF EXISTS public.maru_guard_logistics_restricted_address();",
            "DROP FUNCTION IF EXISTS public.maru_guard_logistics_entity_identity();",
            "DROP FUNCTION IF EXISTS public.maru_logistics_person_is_eligible(uuid, uuid, uuid, uuid);",
            "DROP FUNCTION IF EXISTS public.maru_prevent_logistics_evidence_mutation();",
        )
    )
    return "\n".join(statements)


FORWARD_SQL = (
    CORE_FUNCTION_SQL
    + ADDRESS_FUNCTION_SQL
    + CATALOG_SCOPE_SQL
    + EVIDENCE_SCOPE_SQL
    + STATE_FUNCTION_SQL
    + _install_trigger_sql()
)
REVERSE_SQL = _remove_trigger_sql()

LOGISTICS_MODEL_NAMES = (
    "LogisticsParty",
    "RestrictedLogisticsAddress",
    "EquipmentOffer",
    "EquipmentOfferItem",
    "EquipmentOfferHistory",
    "EquipmentOfferAcceptance",
    "LogisticsNode",
    "Asset",
    "StockLot",
    "PhysicalKey",
    "KeyholderResponsibility",
    "AssetAgreement",
    "ReusableKit",
    "ReusableKitLine",
    "LogisticsManifest",
    "LogisticsManifestLine",
    "LogisticsLabel",
    "LogisticsEvent",
    "LogisticsCurrentState",
    "LogisticsDiscrepancy",
    "LogisticsEditionControl",
    "OfflineScanBatch",
    "OfflineScanOperation",
    "OfflineOperationReceipt",
    "LogisticsCommandReceipt",
)


def refuse_logistics_integrity_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    tables = tuple(
        apps.get_model("logistics", model_name)._meta.db_table
        for model_name in LOGISTICS_MODEL_NAMES
    )
    schema_editor.execute(
        "LOCK TABLE "
        + ", ".join(f"public.{table}" for table in tables)
        + " IN ACCESS EXCLUSIVE MODE"
    )
    if any(
        apps.get_model("logistics", model_name).objects.exists()
        for model_name in LOGISTICS_MODEL_NAMES
    ):
        raise RuntimeError(
            "Cannot remove Logistics database integrity after durable catalog, "
            "custody, contact, manifest, or command evidence exists; keep "
            "compatible code and fix forward."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0016_logistics_capabilities_and_resource_kind"),
        ("logistics", "0001_initial"),
        ("venues", "0001_initial"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_logistics_integrity_downgrade,
        ),
    ]
