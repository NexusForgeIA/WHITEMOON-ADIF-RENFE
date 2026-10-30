import engine


def test_decel_no_menos_conservadora_que_etcs_adherencia_reducida():
    # ETC ETCS (FN) v1.0, Anexo D, paquete 203: A_NVMAXREDADH2/3 = 0,7 m/s². RailGuard debe frenar igual o peor.
    assert engine.DEFAULT_CFG["decel_service"] <= 0.7
