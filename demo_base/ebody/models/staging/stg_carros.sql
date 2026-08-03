select
  id_carro,
  nm_modelo,
  cd_marca
from {{ source('frota', 'carros') }}
