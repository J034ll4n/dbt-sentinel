select
  id_viagem,
  id_carro,
  id_motorista,
  qt_km,
  vr_custo
from {{ ref('stg_carros') }}
