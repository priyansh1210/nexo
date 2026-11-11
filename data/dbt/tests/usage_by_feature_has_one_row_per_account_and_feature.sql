select account_id, feature, count(*) as rows_found
from {{ ref('fct_usage_by_feature') }}
group by account_id, feature
having count(*) > 1
