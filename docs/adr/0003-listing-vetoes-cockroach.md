# Listing vetoes live in Cockroach, not git

Hide/Park must be writable from the Vercel dashboard and readable by the GitHub Actions bot without committing mid-flight. A git `data/*.json` veto file would reintroduce the same push races as hunt state and would not update the live desk until Actions commits. Cockroach already backs scored listings for the dashboard, so `listing_vetoes` keyed by `item_id` is the shared write model; git JSON remains a cache of hunt outputs only.
