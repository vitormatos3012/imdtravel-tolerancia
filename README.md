# IMDTravel - Parte 1 (baseline)

## Membros da equipe

 - João Vitor Matos de Souza
 - Tanhleno Teixeira de Sousa

## Linguagem e Framework

 - Python 3.12
 - Flask

## Testes realizados

Primeiramente, foram realizados testes manuais, documentados em [testes-manuais-com-curl.md](tests/evidencias/testes-manuais-com-curl.md). Em seguida, o script de testes automatizados foi executado na implementação desenvolvida, utilizando o ambiente definido em [docker-compose.yml](docker-compose.yml), com os resultados registrados em [testes-automatizados.txt](tests/evidencias/imdtravel/testes-automatizados.txt). Por fim, os testes com `--com-falhas` foram executados tanto na implementação desenvolvida quanto na imagem de referência do professor, utilizando, respectivamente, `docker-compose.yml` e `docker-compose.hub.yml`. Os resultados dessa comparação estão documentados em [testes-comparativos.md](tests/evidencias/testes-comparativos.md).

## Catálogo de voos usado

Os testes foram realizados com o catálogo padrão (*baseline*) do professor, sem alterações nas variáveis de ambiente. Foram utilizados três voos (IMD100, IMD200 e IMD300), durante sete dias (01/12/2026 a 07/12/2026), com 20 assentos por voo/dia. Os preços possuem acréscimo diário de US$ 12,25 e a taxa de câmbio inicial é de R$ 5,50 por dólar, atualizada a cada 10 segundos.