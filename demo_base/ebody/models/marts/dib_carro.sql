select
  id_carro,
  nm_modelo,
  cd_marca
from {{ ref('stg_carros') }}
