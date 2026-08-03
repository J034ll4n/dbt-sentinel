select
  id_motorista,
  nm_motorista
from {{ source('frota', 'motoristas') }}
