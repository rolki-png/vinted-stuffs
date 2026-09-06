// @ts-nocheck
import { VintedClient } from '@googlarz/vinted-client'

let client = null

function getVintedClient() {
  if (!client) client = new VintedClient()
  return client
}

export { getVintedClient }
