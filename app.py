#!/usr/bin/env python3
"""
Sistema Web de Control de Stock y Registro Financiero
Flask + SQLite + Bootstrap (Responsive para móvil)
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
import sqlite3
from datetime import datetime, timedelta
import csv
import os
import io
from contextlib import contextmanager

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'  # Cambia esto en producción

DB_FILE = "stock_finanzas.db"

# --------------------
# Utilidades
# --------------------
def now_iso():
    return datetime.now().isoformat()

def ensure_db_folder():
    folder = os.path.dirname(os.path.abspath(DB_FILE))
    if not os.path.exists(folder):
        os.makedirs(folder)

# --------------------
# Base de datos (misma lógica que Tkinter)
# --------------------
class DB:
    def __init__(self, dbfile=DB_FILE):
        ensure_db_folder()
        self.dbfile = dbfile
        self.init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.dbfile)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS productos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT UNIQUE,
                    nombre TEXT NOT NULL,
                    categoria TEXT,
                    precio_compra REAL DEFAULT 0,
                    precio_venta REAL DEFAULT 0,
                    margen_ganancia REAL DEFAULT 0,
                    stock_actual REAL DEFAULT 0,
                    stock_minimo REAL DEFAULT 0,
                    creado_en TEXT
                )
            ''')
            
            # Agregar columna si no existe
            try:
                c.execute('ALTER TABLE productos ADD COLUMN margen_ganancia REAL DEFAULT 0')
            except sqlite3.OperationalError:
                pass
                
            c.execute('''
                CREATE TABLE IF NOT EXISTS movimientos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT,
                    producto_id INTEGER,
                    tipo TEXT,
                    cantidad REAL,
                    comentario TEXT,
                    usuario TEXT,
                    creado_en TEXT,
                    FOREIGN KEY(producto_id) REFERENCES productos(id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS finanzas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT,
                    tipo TEXT,
                    monto REAL,
                    concepto TEXT,
                    categoria TEXT,
                    movimiento_id INTEGER,
                    creado_en TEXT
                )
            ''')
            conn.commit()

    def add_producto(self, codigo, nombre, categoria, precio_compra, precio_venta, margen_ganancia, stock_inicial, stock_minimo):
        with self.get_connection() as conn:
            cur = conn.execute('''
                INSERT INTO productos (codigo,nombre,categoria,precio_compra,precio_venta,margen_ganancia,stock_actual,stock_minimo,creado_en)
                VALUES (?,?,?,?,?,?,?,?,?)
            ''', (codigo, nombre, categoria, precio_compra, precio_venta, margen_ganancia, stock_inicial, stock_minimo, now_iso()))
            conn.commit()
            return cur.lastrowid

    def listar_productos(self, search=None):
        with self.get_connection() as conn:
            c = conn.cursor()
            if search:
                q = f"%{search}%"
                c.execute('SELECT * FROM productos WHERE nombre LIKE ? OR codigo LIKE ? OR categoria LIKE ? ORDER BY nombre', (q, q, q))
            else:
                c.execute('SELECT * FROM productos ORDER BY nombre')
            return c.fetchall()

    def get_producto(self, producto_id):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM productos WHERE id=?', (producto_id,))
            return c.fetchone()

    def update_producto(self, producto_id, **kwargs):
        if not kwargs:
            return
        keys = []
        vals = []
        for k, v in kwargs.items():
            keys.append(f"{k}=?")
            vals.append(v)
        vals.append(producto_id)
        sql = f"UPDATE productos SET {', '.join(keys)} WHERE id=?"
        with self.get_connection() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def delete_producto(self, producto_id):
        with self.get_connection() as conn:
            conn.execute('DELETE FROM productos WHERE id=?', (producto_id,))
            conn.execute('DELETE FROM movimientos WHERE producto_id=?', (producto_id,))
            conn.commit()

    def add_movimiento(self, producto_id, tipo, cantidad, comentario, usuario, fecha=None, link_finanza=True):
        if fecha is None:
            fecha = now_iso()
        with self.get_connection() as conn:
            cur = conn.execute('''
                INSERT INTO movimientos (fecha,producto_id,tipo,cantidad,comentario,usuario,creado_en)
                VALUES (?,?,?,?,?,?,?)
            ''', (fecha, producto_id, tipo, cantidad, comentario, usuario, now_iso()))
            mid = cur.lastrowid
            
            # Actualizar stock
            if tipo.lower() == 'entrada':
                conn.execute('UPDATE productos SET stock_actual = stock_actual + ? WHERE id=?', (cantidad, producto_id))
            elif tipo.lower() == 'salida':
                conn.execute('UPDATE productos SET stock_actual = stock_actual - ? WHERE id=?', (cantidad, producto_id))
            elif tipo.lower() == 'ajuste':
                conn.execute('UPDATE productos SET stock_actual = ? WHERE id=?', (cantidad, producto_id))
            
            if link_finanza:
                prod = self.get_producto(producto_id)
                if prod:
                    if tipo.lower() == 'salida':
                        pv = prod['precio_venta'] or 0
                        pc = prod['precio_compra'] or 0
                        
                        if pv > 0:
                            ingreso_bruto = pv * cantidad
                            concepto_ingreso = f"Venta: {prod['nombre']} x{cantidad} a ${pv:.2f} c/u"
                            conn.execute('''
                                INSERT INTO finanzas (fecha,tipo,monto,concepto,categoria,movimiento_id,creado_en) 
                                VALUES (?,?,?,?,?,?,?)
                            ''', (fecha, 'Ingreso', ingreso_bruto, concepto_ingreso, 'Ingresos', mid, now_iso()))
                        
                        if pv > pc:
                            ganancia_neta = (pv - pc) * cantidad
                            concepto_ganancia = f"Ganancia neta: {prod['nombre']} x{cantidad}"
                            conn.execute('''
                                INSERT INTO finanzas (fecha,tipo,monto,concepto,categoria,movimiento_id,creado_en) 
                                VALUES (?,?,?,?,?,?,?)
                            ''', (fecha, 'Ingreso', ganancia_neta, concepto_ganancia, 'Ganancias', mid, now_iso()))
                    
                    elif tipo.lower() == 'entrada':
                        pc = prod['precio_compra'] or 0
                        if pc > 0:
                            monto_compra = pc * cantidad
                            concepto_compra = f"Compra: {prod['nombre']} x{cantidad} a ${pc:.2f} c/u"
                            conn.execute('''
                                INSERT INTO finanzas (fecha,tipo,monto,concepto,categoria,movimiento_id,creado_en) 
                                VALUES (?,?,?,?,?,?,?)
                            ''', (fecha, 'Egreso', monto_compra, concepto_compra, 'Compras', mid, now_iso()))
            
            conn.commit()
            return mid

    def listar_movimientos(self, limit=None):
        with self.get_connection() as conn:
            c = conn.cursor()
            sql = '''SELECT m.*, p.nombre as producto_nombre, p.codigo as producto_codigo 
                     FROM movimientos m LEFT JOIN productos p ON p.id=m.producto_id 
                     ORDER BY m.fecha DESC'''
            if limit:
                sql += f' LIMIT {int(limit)}'
            c.execute(sql)
            return c.fetchall()

    def add_finanza(self, tipo, monto, concepto, categoria=None, movimiento_id=None, fecha=None):
        if fecha is None:
            fecha = now_iso()
        with self.get_connection() as conn:
            cur = conn.execute('''
                INSERT INTO finanzas (fecha,tipo,monto,concepto,categoria,movimiento_id,creado_en) 
                VALUES (?,?,?,?,?,?,?)
            ''', (fecha, tipo, monto, concepto, categoria, movimiento_id, now_iso()))
            conn.commit()
            return cur.lastrowid

    def listar_finanzas(self, limit=None):
        with self.get_connection() as conn:
            c = conn.cursor()
            sql = 'SELECT * FROM finanzas ORDER BY fecha DESC'
            if limit:
                sql += f' LIMIT {int(limit)}'
            c.execute(sql)
            return c.fetchall()

    def delete_finanza(self, finanza_id):
        with self.get_connection() as conn:
            conn.execute('DELETE FROM finanzas WHERE id=?', (finanza_id,))
            conn.commit()

    def balance_total(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT 
                    SUM(CASE WHEN tipo='Ingreso' AND categoria='Ingresos' THEN monto ELSE 0 END) as ingresos_brutos_ventas,
                    SUM(CASE WHEN tipo='Ingreso' AND categoria='Ganancias' THEN monto ELSE 0 END) as ganancias_netas,
                    SUM(CASE WHEN tipo='Ingreso' AND categoria NOT IN ('Ingresos', 'Ganancias') THEN monto ELSE 0 END) as otros_ingresos,
                    SUM(CASE WHEN tipo='Egreso' THEN monto ELSE 0 END) as total_egresos
                FROM finanzas
            ''')
            r = c.fetchone()
            
            ingresos_ventas = r['ingresos_brutos_ventas'] or 0
            ganancias_netas = r['ganancias_netas'] or 0
            otros_ingresos = r['otros_ingresos'] or 0
            total_egresos = r['total_egresos'] or 0
            
            ingresos_brutos = ingresos_ventas + otros_ingresos
            balance = ingresos_brutos - total_egresos
            
            return {
                'ingresos_brutos': ingresos_brutos,
                'ingresos_ventas': ingresos_ventas,
                'otros_ingresos': otros_ingresos,
                'ganancias_netas': ganancias_netas,
                'egresos': total_egresos,
                'balance': balance
            }

    def stock_bajo(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM productos WHERE stock_actual <= stock_minimo ORDER BY stock_actual')
            return c.fetchall()

# Instanciar base de datos
db = DB()

# --------------------
# RUTAS WEB
# --------------------

@app.route('/')
def index():
    """Dashboard principal"""
    balance_data = db.balance_total()
    productos_bajo = db.stock_bajo()
    movimientos_recientes = db.listar_movimientos(limit=5)
    
    return render_template('dashboard.html', 
                         balance=balance_data,
                         productos_bajo=len(productos_bajo),
                         movimientos=movimientos_recientes)

@app.route('/productos')
def productos():
    """Lista de productos"""
    search = request.args.get('search', '')
    productos_list = db.listar_productos(search=search if search else None)
    return render_template('productos.html', productos=productos_list, search=search)

@app.route('/productos/nuevo', methods=['GET', 'POST'])
def nuevo_producto():
    """Agregar nuevo producto"""
    if request.method == 'POST':
        try:
            codigo = request.form.get('codigo')
            nombre = request.form.get('nombre')
            categoria = request.form.get('categoria')
            precio_compra = float(request.form.get('precio_compra', 0))
            precio_venta = float(request.form.get('precio_venta', 0))
            margen = float(request.form.get('margen_ganancia', 0))
            stock_inicial = float(request.form.get('stock_inicial', 0))
            stock_minimo = float(request.form.get('stock_minimo', 0))
            
            if not precio_venta and margen:
                precio_venta = precio_compra * (1 + margen / 100)
            
            db.add_producto(codigo, nombre, categoria, precio_compra, precio_venta, margen, stock_inicial, stock_minimo)
            flash('Producto agregado exitosamente', 'success')
            return redirect(url_for('productos'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('producto_form.html', titulo='Nuevo Producto')

@app.route('/productos/<int:producto_id>/editar', methods=['GET', 'POST'])
def editar_producto(producto_id):
    """Editar producto"""
    producto = db.get_producto(producto_id)
    if not producto:
        flash('Producto no encontrado', 'error')
        return redirect(url_for('productos'))
    
    if request.method == 'POST':
        try:
            data = {
                'codigo': request.form.get('codigo'),
                'nombre': request.form.get('nombre'),
                'categoria': request.form.get('categoria'),
                'precio_compra': float(request.form.get('precio_compra', 0)),
                'precio_venta': float(request.form.get('precio_venta', 0)),
                'margen_ganancia': float(request.form.get('margen_ganancia', 0)),
                'stock_actual': float(request.form.get('stock_actual', 0)),
                'stock_minimo': float(request.form.get('stock_minimo', 0))
            }
            
            db.update_producto(producto_id, **data)
            flash('Producto actualizado exitosamente', 'success')
            return redirect(url_for('productos'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('producto_form.html', titulo='Editar Producto', producto=producto)

@app.route('/productos/<int:producto_id>/eliminar', methods=['POST'])
def eliminar_producto(producto_id):
    """Eliminar producto"""
    try:
        db.delete_producto(producto_id)
        flash('Producto eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('productos'))

@app.route('/movimientos')
def movimientos():
    """Lista de movimientos"""
    movimientos_raw = db.listar_movimientos(limit=200)
    # Convertir Row objects a diccionarios
    movimientos_list = []
    for mov in movimientos_raw:
        movimientos_list.append({
            'id': mov['id'],
            'fecha': mov['fecha'],
            'tipo': mov['tipo'],
            'cantidad': mov['cantidad'],
            'producto_nombre': mov['producto_nombre'],
            'producto_codigo': mov['producto_codigo'],
            'comentario': mov['comentario'],
            'usuario': mov['usuario']
        })
    return render_template('movimientos.html', movimientos=movimientos_list)

@app.route('/movimientos/nuevo', methods=['GET', 'POST'])
def nuevo_movimiento():
    """Agregar nuevo movimiento"""
    productos_list = db.listar_productos()
    
    if request.method == 'POST':
        try:
            producto_id = int(request.form.get('producto_id'))
            tipo = request.form.get('tipo')
            cantidad = float(request.form.get('cantidad'))
            comentario = request.form.get('comentario', '')
            usuario = request.form.get('usuario', 'Web')
            
            db.add_movimiento(producto_id, tipo, cantidad, comentario, usuario)
            flash('Movimiento registrado exitosamente', 'success')
            return redirect(url_for('movimientos'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('movimiento_form.html', productos=productos_list)

@app.route('/finanzas')
def finanzas():
    """Lista de finanzas"""
    finanzas_list = db.listar_finanzas(limit=200)
    balance_data = db.balance_total()
    return render_template('finanzas.html', finanzas=finanzas_list, balance=balance_data)

@app.route('/finanzas/nueva', methods=['GET', 'POST'])
def nueva_finanza():
    """Agregar nueva finanza"""
    if request.method == 'POST':
        try:
            tipo = request.form.get('tipo')
            monto = float(request.form.get('monto'))
            concepto = request.form.get('concepto')
            categoria = request.form.get('categoria', 'Otros')
            
            db.add_finanza(tipo, monto, concepto, categoria)
            flash('Finanza registrada exitosamente', 'success')
            return redirect(url_for('finanzas'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('finanza_form.html')

@app.route('/finanzas/<int:finanza_id>/eliminar', methods=['POST'])
def eliminar_finanza(finanza_id):
    """Eliminar finanza"""
    try:
        db.delete_finanza(finanza_id)
        flash('Registro eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('finanzas'))

@app.route('/reportes')
def reportes():
    """Página de reportes"""
    stock_bajo = db.stock_bajo()
    return render_template('reportes.html', productos_bajo=stock_bajo)

@app.route('/api/calcular_precio')
def api_calcular_precio():
    """API para calcular precios automáticamente"""
    precio_compra = float(request.args.get('precio_compra', 0))
    precio_venta = float(request.args.get('precio_venta', 0))
    margen = float(request.args.get('margen', 0))
    campo = request.args.get('campo')
    
    if campo == 'precio_venta' and precio_compra and margen:
        precio_venta = precio_compra * (1 + margen / 100)
    elif campo == 'margen' and precio_compra and precio_venta:
        margen = ((precio_venta - precio_compra) / precio_compra) * 100 if precio_compra > 0 else 0
    
    return jsonify({
        'precio_venta': round(precio_venta, 2),
        'margen': round(margen, 1)
    })

@app.route('/manifest.json')
def manifest():
    """Servir manifest.json para PWA"""
    return send_file('static/manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def service_worker():
    """Servir service worker"""
    return send_file('static/sw.js', mimetype='application/javascript')
if __name__ == '__main__':
    app.run(debug=False)  # debug=False en producción