# Retail store runtime settings

Store-scoped generated retail clients read their destination from the runtime
environment instead of carrying a default store, warehouse, ZIP, state or
locality. The deployment supplies the values from a root-owned file outside the
repository, `/etc/ghostship/retail-store.env` (mode 0600), the same private
pattern as `/etc/ghostship/mcp-identity.env`.

The file is projected into the MCP private-integrations container (the service
executor) and the `t3code` container, which also runs the agent CLI and the
generated clients. No value is stored in this repository.

| Setting | Client | Meaning |
| --- | --- | --- |
| `COSTCO_WAREHOUSE_ID` | costco | Warehouse id for warehouse inventory and price reads. |
| `COSTCO_WEB_WAREHOUSE_ID` | costco | Warehouse delivery location id for Costco.com. |
| `COSTCO_POSTAL_CODE` | costco | Ship-to postal code for Costco.com delivery. |
| `COSTCO_STATE` | costco | Ship-to state code for Costco.com delivery. |
| `SAFEWAY_STORE_ID` | safeway | Safeway store id. |
| `SAFEWAY_POSTAL_CODE` | safeway | ZIP for the Safeway store resolver. |
| `TARGET_DEFAULT_STORE` | target | Target store id. |
| `TARGET_POSTAL_CODE` | target | Target destination ZIP. |
| `TARGET_STATE` | target | Target destination state code. |
| `TARGET_TIMEZONE` | target | Target API timezone; defaults to `UTC`. |
| `WALMART_STORE_ID` | walmart | Walmart store id. |
| `WALMART_POSTAL_CODE` | walmart | Walmart destination ZIP. |
| `HOMEDEPOT_STORE_ID` | homedepot | Home Depot store id. |
| `HOMEDEPOT_POSTAL_CODE` | homedepot | Home Depot destination ZIP. |
| `HOMEDEPOT_STATE` | homedepot | Home Depot destination state code. |
| `BESTBUY_POSTAL_CODE` | bestbuy | Best Buy destination ZIP. |

A missing required setting fails locally with a usage error naming the flag and
the setting; it is not sent upstream as an empty value.

The owner creates the file on the host with the values; it is never committed.
