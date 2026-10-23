import os
from functools import wraps

from dotenv import load_dotenv



from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash,
    session,
)

from werkzeug.security import check_password_hash

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text


load_dotenv()


app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("RENDER") == "true"
)

BASE_DIR = Path(__file__).resolve().parent

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"sqlite:///{BASE_DIR / 'gastos.db'}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Periodo(db.Model):
    __tablename__ = "periodos"

    id = db.Column(db.Integer, primary_key=True)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=True)
    total_centavos = db.Column(db.Integer, default=0, nullable=False)
    quantidade_gastos = db.Column(db.Integer, default=0, nullable=False)

    gastos = db.relationship("Gasto", backref="periodo", lazy=True)


class Gasto(db.Model):
    __tablename__ = "gastos"

    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(120), nullable=False)
    valor_centavos = db.Column(db.Integer, nullable=False)

    periodo_id = db.Column(
        db.Integer,
        db.ForeignKey("periodos.id"),
        nullable=True
    )


def obter_periodo_atual():
    return Periodo.query.filter_by(data_fim=None).order_by(
        Periodo.id.desc()
    ).first()


def inicializar_banco():
    db.create_all()

    # Migração para bancos SQLite já existentes.
    # Adiciona a coluna sem apagar os gastos cadastrados.
    colunas = db.session.execute(
        text("PRAGMA table_info(gastos)")
    ).fetchall()

    nomes_colunas = {coluna[1] for coluna in colunas}

    if "periodo_id" not in nomes_colunas:
        db.session.execute(
            text("ALTER TABLE gastos ADD COLUMN periodo_id INTEGER")
        )
        db.session.commit()

    # Cria o primeiro período se ainda não existir.
    periodo = obter_periodo_atual()

    if periodo is None:
        periodo = Periodo(data_inicio=date.today())
        db.session.add(periodo)
        db.session.flush()

    # Vincula os gastos antigos ao período inicial.
    db.session.execute(
        text(
            "UPDATE gastos SET periodo_id = :periodo_id "
            "WHERE periodo_id IS NULL"
        ),
        {"periodo_id": periodo.id}
    )

    db.session.commit()



def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("usuario_logado"):
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper




@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_logado"):
        return redirect(url_for("index"))

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")

        usuario_correto = os.getenv("LOGIN_USERNAME", "")
        senha_hash = os.getenv("LOGIN_PASSWORD_HASH", "")

        if not usuario_correto or not senha_hash:
            flash(
                "O login ainda não foi configurado corretamente.",
                "erro",
            )
            return render_template("login.html")

        if (
            usuario == usuario_correto
            and check_password_hash(senha_hash, senha)
        ):
            session.clear()
            session["usuario_logado"] = usuario

            flash("Login realizado com sucesso!", "sucesso")
            return redirect(url_for("index"))

        flash("Usuário ou senha incorretos.", "erro")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required

def logout():
    session.clear()
    flash("Você saiu da sua conta.", "sucesso")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    periodo = obter_periodo_atual()

    gastos = (
        Gasto.query
        .filter_by(periodo_id=periodo.id)
        .order_by(Gasto.id.desc())
        .all()
    )

    # Total e quantidade de despesas atuais
    total_centavos = sum(
        gasto.valor_centavos for gasto in gastos
    )
    quantidade_gastos = len(gastos)

    # Média diária desde o início do período
    hoje = date.today()
    dias_decorridos = max(
        (hoje - periodo.data_inicio).days + 1,
        1
    )
    media_diaria_centavos = round(
        total_centavos / dias_decorridos
    )

    # Período encerrado anterior
    periodo_anterior = (
        Periodo.query
        .filter(
            Periodo.data_fim.isnot(None),
            Periodo.id < periodo.id
        )
        .order_by(Periodo.id.desc())
        .first()
    )

    total_anterior = (
        periodo_anterior.total_centavos
        if periodo_anterior else None
    )

    # Comparação percentual
    variacao_percentual = None

    if total_anterior is not None and total_anterior > 0:
        variacao_percentual = (
            (total_centavos - total_anterior)
            / total_anterior
        ) * 100

    return render_template(
        "index.html",
        gastos=gastos,
        total_centavos=total_centavos,
        periodo=periodo,
        quantidade_gastos=quantidade_gastos,
        media_diaria_centavos=media_diaria_centavos,
        total_anterior=total_anterior,
        variacao_percentual=variacao_percentual,
    )


@app.route("/adicionar", methods=["POST"])
@login_required
def adicionar():
    descricao = request.form.get("descricao", "").strip()
    valor_texto = request.form.get("valor", "").strip()

    if not descricao or len(descricao) > 120:
        flash("Informe uma descrição válida.", "erro")
        return redirect(url_for("index"))

    try:
        valor_texto = (
            valor_texto.replace("R$", "").replace(" ", "")
        )

        if "," in valor_texto:
            valor_texto = valor_texto.replace(".", "")
            valor_texto = valor_texto.replace(",", ".")

        valor = Decimal(valor_texto)

        if not valor.is_finite() or valor <= 0:
            raise InvalidOperation

        valor_centavos = int(valor * 100)

    except (InvalidOperation, ValueError):
        flash("Digite um valor válido.", "erro")
        return redirect(url_for("index"))

    periodo = obter_periodo_atual()

    gasto = Gasto(
        descricao=descricao,
        valor_centavos=valor_centavos,
        periodo_id=periodo.id
    )

    try:
        db.session.add(gasto)
        db.session.commit()
        flash("Gasto salvo com sucesso!", "sucesso")
    except Exception:
        db.session.rollback()
        flash("Não foi possível salvar o gasto.", "erro")

    return redirect(url_for("index"))


@app.route("/excluir/<int:gasto_id>", methods=["POST"])
@login_required
def excluir(gasto_id):
    gasto = db.session.get(Gasto, gasto_id)

    if gasto is None:
        flash("Gasto não encontrado.", "erro")
        return redirect(url_for("index"))

    periodo_atual = obter_periodo_atual()

    # Não permite excluir despesas de períodos encerrados.
    if periodo_atual is None or gasto.periodo_id != periodo_atual.id:
        flash("Não é possível excluir gastos de períodos encerrados.", "erro")
        return redirect(url_for("historico"))

    try:
        db.session.delete(gasto)
        db.session.commit()
        flash("Gasto excluído.", "sucesso")
    except Exception:
        db.session.rollback()
        flash("Não foi possível excluir o gasto.", "erro")

    return redirect(url_for("index"))


@app.route("/encerrar-periodo", methods=["POST"])
@login_required
def encerrar_periodo():
    periodo = obter_periodo_atual()

    if periodo is None:
        flash("Não foi possível localizar o período atual.", "erro")
        return redirect(url_for("index"))

    gastos = Gasto.query.filter_by(
        periodo_id=periodo.id
    ).all()

    if not gastos:
        flash("Adicione pelo menos um gasto antes de encerrar o período.", "erro")
        return redirect(url_for("index"))

    try:
        # Congela o resumo do período que está sendo encerrado.
        periodo.total_centavos = sum(
            gasto.valor_centavos for gasto in gastos
        )
        periodo.quantidade_gastos = len(gastos)
        periodo.data_fim = date.today()

        # Abre outro período sem apagar o histórico anterior.
        novo_periodo = Periodo(data_inicio=date.today())
        db.session.add(novo_periodo)
        db.session.commit()

        flash("Período encerrado e resumo salvo com sucesso!", "sucesso")
        return redirect(url_for("historico"))

    except Exception:
        db.session.rollback()
        flash("Erro ao encerrar o período. Tente novamente.", "erro")
        return redirect(url_for("index"))




@app.route("/historico/<int:periodo_id>/excluir", methods=["POST"])
@login_required
def excluir_periodo(periodo_id):
    periodo = db.session.get(Periodo, periodo_id)

    if periodo is None:
        flash("Período não encontrado.", "erro")
        return redirect(url_for("historico"))

    # Só permite excluir períodos finalizados.
    if periodo.data_fim is None:
        flash("Não é possível excluir o período atual.", "erro")
        return redirect(url_for("index"))

    try:
        # Exclui somente os gastos vinculados a este período.
        Gasto.query.filter_by(
            periodo_id=periodo.id
        ).delete(synchronize_session=False)

        # Exclui o resumo do período selecionado.
        db.session.delete(periodo)
        db.session.commit()

        flash("Período e seus gastos excluídos com sucesso!", "sucesso")

    except Exception:
        db.session.rollback()
        flash("Não foi possível excluir o período.", "erro")

    return redirect(url_for("historico"))



@app.route("/historico")
@login_required
def historico():
    periodos = Periodo.query.filter(
        Periodo.data_fim.isnot(None)
    ).order_by(Periodo.data_fim.desc(), Periodo.id.desc()).all()

    return render_template("historico.html", periodos=periodos)


@app.route("/historico/<int:periodo_id>")
@login_required
def detalhes_periodo(periodo_id):
    periodo = db.get_or_404(Periodo, periodo_id)

    if periodo.data_fim is None:
        flash("Este período ainda está aberto.", "erro")
        return redirect(url_for("index"))

    gastos = Gasto.query.filter_by(
        periodo_id=periodo.id
    ).order_by(Gasto.id.desc()).all()

    return render_template(
        "detalhes_periodo.html",
        periodo=periodo,
        gastos=gastos
    )


with app.app_context():
    inicializar_banco()


if __name__ == "__main__":
    app.run(debug=True)
