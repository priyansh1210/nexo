-- One customer, three systems: the CRM account, the product workspace and the support organisation.
select account_id, workspace_id, support_org_id
from {{ ref('stg_accounts') }}
