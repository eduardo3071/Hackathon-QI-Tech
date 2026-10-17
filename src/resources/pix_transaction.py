from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PixTransactionController
from utils.schema_handler import SchemaHandler


class PixTransactionResource:
    """A porta de entrada HTTP do motor antifraude.

    Três coisas, nesta ordem, e nada além: conferir o corpo (o decorator
    do schema), chamar o controller, devolver o que ele respondeu. Nenhum
    `if` sobre o Pix mora aqui — inclusive a recusa antifraude, que NÃO é
    erro HTTP: o Pix foi analisado com sucesso, e a resposta é 201 com
    `status: rejected`.

    O status HTTP, esse sim, é decidido aqui: 201 quando a análise nasceu
    agora, 200 quando o mesmo Pix chegou de novo e a análise já existia.
    Quem sabe qual dos dois aconteceu é o controller; quem traduz isso
    em número de HTTP é o resource.
    """

    @SchemaHandler.validate("post_pix_transaction.json")
    def on_post(self, payload: dict) -> JSONResponse:
        controller = PixTransactionController()
        analysis, was_created = controller.create(payload)

        if was_created:
            response_status = http_status.HTTP_201_CREATED
        else:
            response_status = http_status.HTTP_200_OK

        return JSONResponse(content=jsonable_encoder(analysis), status_code=response_status)

    def on_get_by_id(self, pix_id: str) -> JSONResponse:
        controller = PixTransactionController()
        analysis = controller.get_by_id(pix_id)

        return JSONResponse(content=jsonable_encoder(analysis), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("patch_pix_transaction.json")
    def on_patch(self, pix_id: str, payload: dict) -> JSONResponse:
        """O retorno do 2FA. Responde 200 também quando o mesmo resultado chega de novo."""
        controller = PixTransactionController()
        analysis = controller.apply_two_factor_result(pix_id, payload)

        return JSONResponse(content=jsonable_encoder(analysis), status_code=http_status.HTTP_200_OK)
