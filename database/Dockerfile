# Imagem oficial e publica do PostgreSQL.
FROM postgres:16

# Mesmos valores do docker-compose.yml. O compose sobrescreve; estes padroes
# existem para a imagem subir tambem quando rodada sozinha (docker run, ou o
# botao Run do Docker Desktop), sem o erro "superuser password is not
# specified". Valem so para desenvolvimento local.
ENV POSTGRES_USER=bootcamp \
    POSTGRES_PASSWORD=bootcamp \
    POSTGRES_DB=bootcamp

# Todo arquivo .sql colocado aqui roda sozinho quando o banco nasce.
# E assim que as tabelas do projeto sao criadas.
COPY database.sql /docker-entrypoint-initdb.d/01.sql
