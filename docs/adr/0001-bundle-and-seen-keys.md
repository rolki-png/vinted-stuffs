# Bundle checkout extra and per-hunt seen keys

A 40 GBP clothing keep plus fees is a bad checkout, so we treat one seller as one checkout: clothing solo floor 100 GBP, closet crawl only when a new listing id appears, extras at score ≥ 6. Seen state is listing+hunt so a new hunt can revive an old closet item; bare `seen_ids` stay only as a legacy suppress from earlier runs.

Checkout extra is a fixed guess by catalog country because the search API does not quote shipping.

A bundle can mix this run's scores with still-listed prior finds in `data/bundle_pool.json`. Sold or vanished listings are dropped after a live item check. Already-alerted bundle fingerprints are not sent again.
