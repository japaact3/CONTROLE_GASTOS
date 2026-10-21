from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from decimal import Decimal, InvalidOperation
from pathlib import Path

app = Flask(__name__)
app.config["SECRET_KEY"] = "controle-gastos-local"

BASE_DIR = Path(__file__).resolve().parent

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"sqlite:///{BASE_DIR / 'gastos.db'}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Gasto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(120), nullable=False)
    valor_centavos = db.Column(db.Integer, nullable=False)


@app.route("/")
def index():
    gastos = Gasto.query.order_by(Gasto.id.desc()).all()

    total_centavos = sum(g.valor_centavos for g in gastos)

    return render_template(
        "index.html",
        gastos=gastos,
        total_centavos=total_centavos
    )


@app.route("/adicionar", methods=["POST"])
def adicionar():
    descricao = request.form.get("descricao", "").strip()
    valor_texto = request.form.get("valor", "").strip()

    if not descricao or len(descricao) > 120:
        flash("Informe uma descrição válida.", "erro")
        return redirect(url_for("index"))

    try:
        # Aceita valores como 3000,00 ou 3000.00
        valor_texto = valor_texto.replace("R$", "").replace(" ", "")

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

    gasto = Gasto(
        descricao=descricao,
        valor_centavos=valor_centavos
    )

    db.session.add(gasto)
    db.session.commit()

    flash("Gasto salvo com sucesso!", "sucesso")
    return redirect(url_for("index"))


@app.route("/excluir/<int:gasto_id>", methods=["POST"])
def excluir(gasto_id):
    gasto = db.session.get(Gasto, gasto_id)

    if gasto is None:
        flash("Gasto não encontrado.", "erro")
    else:
        db.session.delete(gasto)
        db.session.commit()
        flash("Gasto excluído.", "sucesso")

    return redirect(url_for("index"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
