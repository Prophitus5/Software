import os, re
import secrets
import unicodedata
from urllib.parse import quote
from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pwdlib import PasswordHash
from .db import get_db
from .models import Usuario, Libro, Lector, Prestamo, OrdenReclamo, Configuracion

app = FastAPI(title="Sistema Biblioteca", version="1.0.0", description="Gestión de préstamos, multas y reclamos domiciliarios.")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-only-change-me"), https_only=os.getenv("COOKIE_SECURE", "false").lower()=="true", same_site="lax", max_age=28800)
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
hasher = PasswordHash.recommended()

def current_user(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("uid")
    user = db.get(Usuario, uid) if uid else None
    if not user or not user.activo: raise HTTPException(401, "Inicia sesión para continuar")
    return user

def roles(*allowed):
    def check(user: Usuario = Depends(current_user)):
        if user.rol not in allowed: raise HTTPException(403, "No tienes permisos para esta acción")
        return user
    return check

def page_context(request: Request, db: Session, **extra):
    request.session.setdefault("csrf", secrets.token_urlsafe(32))
    return {"user": db.get(Usuario, request.session["uid"]), "csrf": request.session["csrf"], **extra}

def check_csrf(request: Request, token: str):
    if not secrets.compare_digest(token, request.session.get("csrf", "")):
        raise HTTPException(403, "El formulario venció. Recarga la página e inténtalo de nuevo.")

def normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold().strip())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.split())

def search_match(q: str, *columns):
    pattern=f"%{q.upper()}%"
    return or_(*(func.upper(column).like(pattern) for column in columns))

def reader_search_match(q: str):
    pattern=f"%{q.upper()}%"
    predicates=[func.upper(Lector.nombre).like(pattern),func.upper(Lector.telefono).like(pattern)]
    if re.fullmatch(r"\d{1,6}",q): predicates.append(func.upper(Lector.dni).like(pattern))
    elif re.fullmatch(r"\d{7,8}",q): predicates.append(func.upper(Lector.dni)==q)
    return or_(*predicates)

def phone_digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())

def flash_redirect(path: str, message: str, kind: str = "success"):
    return RedirectResponse(f"{path}?mensaje={quote(message)}&tipo={quote(kind)}", 303)

@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session=Depends(get_db)):
    if not request.session.get("uid"): return RedirectResponse("/login", 303)
    request.session.setdefault("csrf", secrets.token_urlsafe(32))
    signed_in=db.get(Usuario,request.session["uid"])
    if signed_in.rol=="RECLAMADOR":
        own=OrdenReclamo.asignado_a_usuario_id==signed_in.id
        counts={"mis_ordenes":db.scalar(select(func.count()).select_from(OrdenReclamo).where(own)),"pendientes":db.scalar(select(func.count()).select_from(OrdenReclamo).where(own,OrdenReclamo.estado.in_(["PENDIENTE","ASIGNADA"]))),"en_ruta":db.scalar(select(func.count()).select_from(OrdenReclamo).where(own,OrdenReclamo.estado=="EN_RUTA")),"visitas":db.scalar(select(func.count()).select_from(OrdenReclamo).where(own,OrdenReclamo.estado.in_(["VISITADA_EXITOSA","VISITADA_FALLIDA"])))}
    else:
        counts={"activos":db.scalar(select(func.count()).select_from(Prestamo).where(Prestamo.estado=="ACTIVO")),"vencidos":db.scalar(select(func.count()).select_from(Prestamo).where(Prestamo.estado=="ACTIVO",Prestamo.fecha_vencimiento<date.today())),"disponibles":db.scalar(select(func.count()).select_from(Libro).where(Libro.estado=="DISPONIBLE",Libro.activo.is_(True))),"multas":db.scalar(select(func.coalesce(func.sum(Prestamo.multa_monto),0)).where(Prestamo.multa_estado=="PENDIENTE")),"ordenes_abiertas":db.scalar(select(func.count()).select_from(OrdenReclamo).where(OrdenReclamo.estado.in_(["PENDIENTE","ASIGNADA","EN_RUTA"]))) or 0}
    context = page_context(request, db, counts=counts)
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)

@app.get("/buscar")
def buscar_en_vivo(q: str="", db:Session=Depends(get_db), user:Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    q=" ".join(q.strip().split())[:100]
    words=[part for part in q.split() if len(part)>1][:5]
    if not words: return []
    book_cols=(Libro.codigo,Libro.titulo,Libro.autor)
    book_filter=and_(*(search_match(word,*book_cols) for word in words))
    exact_code=(func.upper(Libro.codigo)==q.upper()).desc()
    books=db.scalars(select(Libro).where(book_filter,Libro.activo.is_(True)).order_by(exact_code,Libro.titulo).limit(6)).all()
    people_filter=and_(*(reader_search_match(word) for word in words))
    readers=db.scalars(select(Lector).where(people_filter,Lector.activo.is_(True)).order_by(Lector.nombre).limit(6)).all()
    found=[{"tipo":"Libro","texto":f"{book.codigo} · {book.titulo} — {book.autor}","url":f"/panel/libros?q={quote(book.codigo)}"} for book in books]
    found.extend({"tipo":"Lector","texto":f"{reader.nombre} · DNI {reader.dni}","url":f"/panel/lectores?q={quote(reader.dni)}"} for reader in readers)
    return found

@app.get("/panel/libros", response_class=HTMLResponse)
def panel_libros(request: Request, q: str="", db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    q=q.strip()[:100]
    stmt=select(Libro)
    if q:
        stmt=stmt.where(search_match(q,Libro.codigo,Libro.titulo,Libro.autor))
    rows=db.scalars(stmt.order_by(Libro.titulo)).all()
    total=db.scalar(select(func.count()).select_from(Libro)) or 0
    return templates.TemplateResponse(request=request,name="libros.html",context=page_context(request,db,libros=rows,q=q,total=total,now_year=date.today().year,mensaje=request.query_params.get("mensaje"),tipo=request.query_params.get("tipo","success")))

@app.post("/panel/libros")
def panel_crear_libro(request: Request, codigo: str=Form(), titulo: str=Form(), autor: str=Form(), anio_impresion: int=Form(), csrf: str=Form(), db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    check_csrf(request,csrf); codigo=codigo.strip().upper(); titulo=titulo.strip(); autor=autor.strip()
    if not re.fullmatch(r"[A-Z0-9_-]{3,40}",codigo) or not titulo or len(titulo)>250 or not autor or not 1<=anio_impresion<=date.today().year:
        return flash_redirect("/panel/libros","Revisa el código, título, autor y año.","error")
    db.add(Libro(codigo=codigo,titulo=titulo,titulo_normalizado=normalized_title(titulo),autor=autor,anio_impresion=anio_impresion,estado="DISPONIBLE",activo=True))
    try: db.commit()
    except IntegrityError: db.rollback(); return flash_redirect("/panel/libros","Ya existe un libro con ese código o título.","error")
    return flash_redirect("/panel/libros",f"Libro {codigo} registrado.")

@app.get("/panel/lectores", response_class=HTMLResponse)
def panel_lectores(request: Request, q: str="", db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    q=q.strip()[:100]
    stmt=select(Lector)
    if q:
        stmt=stmt.where(reader_search_match(q))
    rows=db.scalars(stmt.order_by(Lector.nombre)).all()
    total=db.scalar(select(func.count()).select_from(Lector)) or 0
    return templates.TemplateResponse(request=request,name="lectores.html",context=page_context(request,db,lectores=rows,q=q,total=total,mensaje=request.query_params.get("mensaje"),tipo=request.query_params.get("tipo","success")))

@app.post("/panel/lectores")
def panel_crear_lector(request: Request, dni: str=Form(), nombre: str=Form(), direccion: str=Form(), telefono: str=Form(), csrf: str=Form(), db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    check_csrf(request,csrf); dni=dni.strip(); nombre=nombre.strip(); direccion=direccion.strip(); telefono=telefono.strip()
    if not re.fullmatch(r"\d{8}",dni) or not re.fullmatch(r"[0-9+()\- ]{6,20}",telefono) or not nombre or not direccion:
        return flash_redirect("/panel/lectores","Revisa el DNI (8 dígitos), el teléfono y los datos obligatorios.","error")
    duplicate_dni=db.scalar(select(Lector.id).where(Lector.dni==dni)) is not None
    phone=phone_digits(telefono)
    duplicate_phone=any(phone_digits(existing)==phone for existing in db.scalars(select(Lector.telefono)))
    if duplicate_dni or duplicate_phone:
        reasons=[]
        if duplicate_dni: reasons.append("el DNI ya está registrado")
        if duplicate_phone: reasons.append("el número de celular ya está registrado")
        return flash_redirect("/panel/lectores","No se pudo registrar: "+" y ".join(reasons)+".","error")
    db.add(Lector(dni=dni,nombre=nombre,direccion=direccion,telefono=telefono,activo=True))
    try: db.commit()
    except IntegrityError:
        db.rollback()
        duplicate_dni=db.scalar(select(Lector.id).where(Lector.dni==dni)) is not None
        return flash_redirect("/panel/lectores","No se pudo registrar: el DNI ya está registrado." if duplicate_dni else "No se pudo registrar porque el DNI o el número de celular ya está registrado.","error")
    return flash_redirect("/panel/lectores",f"Lector {nombre} registrado.")

@app.get("/panel/prestamos", response_class=HTMLResponse)
def panel_prestamos(request: Request, q: str="", db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    q=q.strip()[:100]
    stmt=select(Prestamo,Libro,Lector).join(Libro,Libro.id==Prestamo.libro_id).join(Lector,Lector.id==Prestamo.lector_id)
    if q:
        stmt=stmt.where(or_(search_match(q,Libro.codigo,Libro.titulo,Lector.nombre),reader_search_match(q)))
    loans=db.execute(stmt.order_by(Prestamo.fecha_prestamo.desc())).all()
    libros=db.scalars(select(Libro).where(Libro.activo.is_(True),Libro.estado=="DISPONIBLE").order_by(Libro.titulo)).all()
    lectores=db.scalars(select(Lector).where(Lector.activo.is_(True)).order_by(Lector.nombre)).all()
    vencidos=db.scalar(select(func.count()).select_from(Prestamo).where(Prestamo.estado=="ACTIVO",Prestamo.fecha_vencimiento<date.today())) or 0
    return templates.TemplateResponse(request=request,name="prestamos.html",context=page_context(request,db,prestamos=loans,libros=libros,lectores=lectores,hoy=date.today().isoformat(),q=q,vencidos=vencidos,user_role=user.rol,mensaje=request.query_params.get("mensaje"),tipo=request.query_params.get("tipo","success")))

@app.post("/panel/prestamos")
def panel_nuevo_prestamo(request: Request, libro_id: int=Form(), lector_id: int=Form(), csrf: str=Form(), db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    check_csrf(request,csrf)
    try:
        result=crear_prestamo({"libro_id":libro_id,"lector_id":lector_id},db,user)
    except HTTPException as exc: return flash_redirect("/panel/prestamos",str(exc.detail),"error")
    return flash_redirect("/panel/prestamos",f"Préstamo registrado. Debe devolverse el {date.fromisoformat(result['fecha_vencimiento']).strftime('%d/%m/%Y')}.")

@app.post("/panel/prestamos/{prestamo_id}/devolver")
def panel_devolver(prestamo_id:int,request:Request,csrf:str=Form(),db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    check_csrf(request,csrf)
    try: result=devolver(prestamo_id,{},db,user)
    except HTTPException as exc: return flash_redirect("/panel/prestamos",str(exc.detail),"error")
    return flash_redirect("/panel/prestamos",f"Devolución registrada. Mora: {result['dias_atraso']} días · multa S/ {result['multa_monto']}.")

@app.post("/panel/prestamos/{prestamo_id}/pagar")
def panel_pagar_multa(prestamo_id:int,request:Request,csrf:str=Form(),db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO"))):
    check_csrf(request,csrf)
    try: result=pagar_multa(prestamo_id,db,user)
    except HTTPException as exc:return flash_redirect("/panel/prestamos",str(exc.detail),"error")
    return flash_redirect("/panel/recaudacion",f"Pago de S/ {result['monto']} registrado correctamente.")

@app.get("/panel/recaudacion",response_class=HTMLResponse)
def panel_recaudacion(request:Request,db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO"))):
    paid=db.execute(select(Prestamo,Libro,Lector,Usuario).join(Libro,Libro.id==Prestamo.libro_id).join(Lector,Lector.id==Prestamo.lector_id).outerjoin(Usuario,Usuario.id==Prestamo.pago_registrado_por_usuario_id).where(Prestamo.multa_estado=="PAGADA").order_by(Prestamo.fecha_pago.desc(),Prestamo.id.desc())).all()
    collected=db.scalar(select(func.coalesce(func.sum(Prestamo.multa_monto),0)).where(Prestamo.multa_estado=="PAGADA")) or Decimal("0.00")
    pending=db.scalar(select(func.coalesce(func.sum(Prestamo.multa_monto),0)).where(Prestamo.multa_estado=="PENDIENTE")) or Decimal("0.00")
    return templates.TemplateResponse(request=request,name="recaudacion.html",context=page_context(request,db,pagos=paid,total_pagado=collected,total_pendiente=pending,mensaje=request.query_params.get("mensaje"),tipo=request.query_params.get("tipo","success")))

@app.get("/usuarios", response_class=HTMLResponse)
def panel_usuarios(request: Request, db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO"))):
    rows=db.scalars(select(Usuario).order_by(Usuario.rol,Usuario.nombre)).all()
    return templates.TemplateResponse(request=request,name="usuarios.html",context=page_context(request,db,usuarios=rows,mensaje=request.query_params.get("mensaje"),tipo=request.query_params.get("tipo","success")))

@app.post("/usuarios")
def crear_usuario_panel(request:Request,nombre:str=Form(),email:str=Form(),password:str=Form(),rol:str=Form(),csrf:str=Form(),db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO"))):
    check_csrf(request,csrf); nombre=nombre.strip();email=email.strip().lower();rol=rol.upper()
    if not nombre or len(nombre)>120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or len(password)<10 or rol not in {"BIBLIOTECARIO","RECLAMADOR"}:
        return flash_redirect("/usuarios","Completa los datos. La contraseña debe tener al menos 10 caracteres.","error")
    db.add(Usuario(nombre=nombre,email=email,password_hash=hasher.hash(password),rol=rol,activo=True))
    try: db.commit()
    except IntegrityError: db.rollback();return flash_redirect("/usuarios","Ese correo ya está registrado.","error")
    return flash_redirect("/usuarios",f"Usuario {email} creado con rol {rol}.")

@app.get("/paloma",response_class=HTMLResponse)
def panel_paloma(request:Request,db:Session=Depends(get_db),user:Usuario=Depends(current_user)):
    q=select(OrdenReclamo,Prestamo,Libro,Lector,Usuario).join(Prestamo,Prestamo.id==OrdenReclamo.prestamo_id).join(Libro,Libro.id==Prestamo.libro_id).join(Lector,Lector.id==OrdenReclamo.lector_id).outerjoin(Usuario,Usuario.id==OrdenReclamo.asignado_a_usuario_id).order_by(OrdenReclamo.estado,OrdenReclamo.id.desc())
    if user.rol=="RECLAMADOR": q=q.where(OrdenReclamo.asignado_a_usuario_id==user.id)
    workers=db.scalars(select(Usuario).where(Usuario.rol=="RECLAMADOR",Usuario.activo.is_(True))).all() if user.rol!="RECLAMADOR" else []
    overdue=db.execute(select(Prestamo,Libro,Lector).join(Libro,Libro.id==Prestamo.libro_id).join(Lector,Lector.id==Prestamo.lector_id).where(Prestamo.estado=="ACTIVO",Prestamo.fecha_vencimiento<date.today(),Lector.activo.is_(True))).all() if user.rol!="RECLAMADOR" else []
    daily_rate=db.get(Configuracion,"MULTA_POR_DIA")
    per_day=Decimal(daily_rate.valor) if daily_rate else Decimal("1.00")
    order_rows=db.execute(q).all()
    estimated={order.id:(Decimal(max(0,(date.today()-loan.fecha_vencimiento).days))*per_day).quantize(Decimal("0.01")) for order,loan,book,reader,worker in order_rows}
    return templates.TemplateResponse(request=request,name="paloma.html",context=page_context(request,db,ordenes=order_rows,workers=workers,vencidos=overdue,today=date.today(),multa_por_dia=per_day,estimados=estimated,mensaje=request.query_params.get("mensaje"),tipo=request.query_params.get("tipo","success")))

@app.post("/panel/paloma/crear")
def panel_crear_orden(request:Request,prestamo_id:int=Form(),csrf:str=Form(),db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    check_csrf(request,csrf)
    try: result=crear_orden({"prestamo_id":prestamo_id},db,user)
    except HTTPException as exc:return flash_redirect("/paloma",str(exc.detail),"error")
    return flash_redirect("/paloma",f"Orden de reclamo #{result['id']} creada.")

@app.post("/panel/paloma/{orden_id}/asignar")
def panel_asignar_orden(orden_id:int,request:Request,usuario_id:int=Form(),csrf:str=Form(),db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    check_csrf(request,csrf)
    try: asignar(orden_id,{"usuario_id":usuario_id},db,user)
    except HTTPException as exc:return flash_redirect("/paloma",str(exc.detail),"error")
    return flash_redirect("/paloma",f"Orden #{orden_id} asignada al trabajador.")

@app.post("/panel/paloma/{orden_id}/estado")
def panel_estado_orden(orden_id:int,request:Request,estado:str=Form(),observaciones:str=Form(default=""),csrf:str=Form(),db:Session=Depends(get_db),user:Usuario=Depends(current_user)):
    check_csrf(request,csrf)
    if user.rol not in {"DUENO","BIBLIOTECARIO","RECLAMADOR"}: raise HTTPException(403,"Sin permiso")
    try: estado_orden(orden_id,{"estado":estado,"observaciones":observaciones},db,user)
    except HTTPException as exc:return flash_redirect("/paloma",str(exc.detail),"error")
    return flash_redirect("/paloma",f"Orden #{orden_id}: estado actualizado.")

@app.post("/panel/paloma/{orden_id}/devolver")
def panel_devolucion_reclamador(orden_id:int,request:Request,csrf:str=Form(),db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO","RECLAMADOR"))):
    check_csrf(request,csrf);order=db.get(OrdenReclamo,orden_id)
    if not order or (user.rol=="RECLAMADOR" and order.asignado_a_usuario_id!=user.id): raise HTTPException(404,"Orden no encontrada")
    try: result=devolver(order.prestamo_id,{},db,user)
    except HTTPException as exc:return flash_redirect("/paloma",str(exc.detail),"error")
    return flash_redirect("/paloma",f"Libro recuperado. Multa: S/ {result['multa_monto']}.")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    request.session.setdefault("csrf", secrets.token_urlsafe(32))
    return templates.TemplateResponse(request=request,name="login.html",context={"error":None,"csrf":request.session["csrf"]})

@app.post("/auth/login")
def login(request: Request, email: str=Form(), password: str=Form(), csrf: str=Form(), db: Session=Depends(get_db)):
    if not secrets.compare_digest(csrf, request.session.get("csrf", "")): raise HTTPException(403,"Token de seguridad inválido; recarga el formulario")
    user=db.scalar(select(Usuario).where(Usuario.email==email.lower().strip(),Usuario.activo.is_(True)))
    if not user or not hasher.verify(password,user.password_hash): raise HTTPException(401,"Correo o contraseña incorrectos")
    request.session["uid"]=user.id
    return RedirectResponse("/",303)

@app.post("/auth/logout")
def logout(request: Request, csrf: str=Form()):
    if not secrets.compare_digest(csrf, request.session.get("csrf", "")): raise HTTPException(403,"Token de seguridad inválido")
    request.session.clear(); return RedirectResponse("/login",303)

@app.get("/libros")
def listar_libros(db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    return [{"id":x.id,"codigo":x.codigo,"titulo":x.titulo,"autor":x.autor,"estado":x.estado,"activo":x.activo} for x in db.scalars(select(Libro).order_by(Libro.titulo))]

@app.post("/libros")
def crear_libro(data: dict, db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    codigo=str(data.get("codigo"," ")).strip().upper(); titulo=str(data.get("titulo"," ")).strip(); autor=str(data.get("autor"," ")).strip(); anio=data.get("anio_impresion")
    if not re.fullmatch(r"[A-Z0-9_-]{3,40}",codigo): raise HTTPException(422,"Código inválido")
    if not titulo or len(titulo)>250 or not autor or not isinstance(anio,int) or not 1<=anio<=date.today().year: raise HTTPException(422,"Revisa título, autor y año")
    row=Libro(codigo=codigo,titulo=titulo,titulo_normalizado=" ".join(titulo.casefold().split()),autor=autor,anio_impresion=anio,estado="DISPONIBLE",activo=True)
    db.add(row)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409,"El código o título ya existe")
    return {"id":row.id,"mensaje":"Libro creado"}

@app.post("/lectores")
def crear_lector(data: dict, db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    dni=str(data.get("dni","")); tel=str(data.get("telefono","")); nombre=str(data.get("nombre"," ")).strip(); direccion=str(data.get("direccion"," ")).strip()
    if not re.fullmatch(r"\d{8}",dni) or not re.fullmatch(r"[0-9+\-() ]{6,20}",tel) or not nombre or not direccion: raise HTTPException(422,"DNI, teléfono, nombre y dirección inválidos")
    if db.scalar(select(Lector.id).where(Lector.dni==dni)): raise HTTPException(409,"El DNI ya está registrado")
    phone=phone_digits(tel)
    if any(phone_digits(existing)==phone for existing in db.scalars(select(Lector.telefono))): raise HTTPException(409,"El número de celular ya está registrado")
    row=Lector(dni=dni,nombre=nombre,direccion=direccion,telefono=tel,activo=True); db.add(row)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409,"El DNI o el número de celular ya está registrado")
    return {"id":row.id,"mensaje":"Lector creado"}

@app.post("/prestamos")
def crear_prestamo(data: dict, db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    libro=db.scalar(select(Libro).where(Libro.id==data.get("libro_id")).with_for_update()); lector=db.get(Lector,data.get("lector_id"))
    if not libro or not lector: raise HTTPException(404,"Libro o lector no encontrado")
    if not libro.activo or libro.estado!="DISPONIBLE": raise HTTPException(409,"El libro no está disponible")
    if not lector.activo: raise HTTPException(409,"El lector está inactivo")
    fecha=data.get("fecha_prestamo")
    try: fecha=date.fromisoformat(fecha) if fecha else date.today()
    except ValueError: raise HTTPException(422,"Fecha inválida; usa AAAA-MM-DD")
    if fecha>date.today(): raise HTTPException(422,"La fecha no puede ser futura")
    moroso=db.scalar(select(Prestamo.id).where(Prestamo.lector_id==lector.id,Prestamo.estado=="ACTIVO",Prestamo.fecha_vencimiento<date.today()))
    if moroso: raise HTTPException(409,"El lector tiene un préstamo vencido activo")
    plazo=7
    p=Prestamo(libro_id=libro.id,lector_id=lector.id,fecha_prestamo=fecha,fecha_vencimiento=fecha+timedelta(days=plazo),estado="ACTIVO",dias_atraso=0,multa_monto=Decimal("0.00"),multa_estado="NO_APLICA",registrado_por_usuario_id=user.id)
    libro.estado="PRESTADO"; db.add(p)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409,"El libro ya fue prestado")
    return {"id":p.id,"fecha_vencimiento":p.fecha_vencimiento.isoformat()}

@app.get("/prestamos")
def listar_prestamos(estado: str|None=None, lector_id: int|None=None, libro_id: int|None=None, db: Session=Depends(get_db), user: Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    q=select(Prestamo)
    if estado: q=q.where(Prestamo.estado==estado.upper())
    if lector_id: q=q.where(Prestamo.lector_id==lector_id)
    if libro_id: q=q.where(Prestamo.libro_id==libro_id)
    return [{"id":p.id,"libro_id":p.libro_id,"lector_id":p.lector_id,"fecha_prestamo":p.fecha_prestamo.isoformat(),"fecha_vencimiento":p.fecha_vencimiento.isoformat(),"estado":p.estado,"multa_monto":str(p.multa_monto),"multa_estado":p.multa_estado} for p in db.scalars(q)]

@app.post("/prestamos/{prestamo_id}/devolver")
def devolver(prestamo_id:int,data:dict,db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO","BIBLIOTECARIO","RECLAMADOR"))):
    p=db.scalar(select(Prestamo).where(Prestamo.id==prestamo_id).with_for_update())
    if not p: raise HTTPException(404,"Préstamo no encontrado")
    if p.estado!="ACTIVO": raise HTTPException(409,"El préstamo ya fue devuelto")
    if user.rol=="RECLAMADOR":
        assigned=db.scalar(select(OrdenReclamo.id).where(OrdenReclamo.prestamo_id==p.id,OrdenReclamo.asignado_a_usuario_id==user.id,OrdenReclamo.estado=="VISITADA_EXITOSA"))
        if not assigned: raise HTTPException(403,"Solo puedes registrar un libro recuperado en una visita exitosa asignada a ti")
    try: fecha=date.fromisoformat(data.get("fecha_devolucion",date.today().isoformat()))
    except ValueError: raise HTTPException(422,"Fecha inválida")
    if fecha>date.today() or fecha<p.fecha_prestamo: raise HTTPException(422,"La fecha de devolución no es válida")
    dias=max(0,(fecha-p.fecha_vencimiento).days); monto=Decimal(dias).quantize(Decimal("1"))*Decimal("1.00")
    p.fecha_devolucion=fecha;p.estado="DEVUELTO";p.dias_atraso=dias;p.multa_monto=monto;p.multa_estado="PENDIENTE" if dias else "NO_APLICA"
    libro=db.get(Libro,p.libro_id);libro.estado="DISPONIBLE"
    for o in db.scalars(select(OrdenReclamo).where(OrdenReclamo.prestamo_id==p.id,OrdenReclamo.estado.in_(["PENDIENTE","ASIGNADA","EN_RUTA"]))): o.estado="CANCELADA"
    db.commit(); return {"dias_atraso":dias,"multa_monto":str(monto),"multa_estado":p.multa_estado}

@app.get("/paloma/ordenes")
def listar_ordenes(db:Session=Depends(get_db),user:Usuario=Depends(current_user)):
    q=select(OrdenReclamo)
    if user.rol=="RECLAMADOR": q=q.where(OrdenReclamo.asignado_a_usuario_id==user.id)
    return [{"id":o.id,"prestamo_id":o.prestamo_id,"estado":o.estado,"direccion":o.direccion_snapshot,"telefono":o.telefono_snapshot,"intentos":o.intentos} for o in db.scalars(q)]

@app.post("/paloma/ordenes")
def crear_orden(data:dict,db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    p=db.get(Prestamo,data.get("prestamo_id"))
    if not p or p.estado!="ACTIVO": raise HTTPException(409,"Solo se reclaman préstamos activos")
    if p.fecha_vencimiento>=date.today(): raise HTTPException(409,"El préstamo aún no está vencido")
    l=db.get(Lector,p.lector_id)
    if not l.activo: raise HTTPException(409,"Lector inactivo: no reclamable")
    o=OrdenReclamo(prestamo_id=p.id,lector_id=l.id,direccion_snapshot=l.direccion,telefono_snapshot=l.telefono,estado="PENDIENTE",intentos=0);db.add(o)
    try: db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,"Ya existe una orden abierta")
    return {"id":o.id,"mensaje":"Orden creada"}

@app.post("/paloma/ordenes/{orden_id}/asignar")
def asignar(orden_id:int,data:dict,db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO","BIBLIOTECARIO"))):
    o=db.get(OrdenReclamo,orden_id);u=db.get(Usuario,data.get("usuario_id"))
    if not o or not u:raise HTTPException(404,"Orden o usuario no encontrado")
    if u.rol!="RECLAMADOR" or not u.activo:raise HTTPException(422,"Asigna a un reclamador activo")
    o.asignado_a_usuario_id=u.id;o.fecha_asignacion=func.current_timestamp();o.estado="ASIGNADA";db.commit();return {"mensaje":"Orden asignada"}

@app.post("/paloma/ordenes/{orden_id}/estado")
def estado_orden(orden_id:int,data:dict,db:Session=Depends(get_db),user:Usuario=Depends(current_user)):
    o=db.get(OrdenReclamo,orden_id)
    if user.rol!="RECLAMADOR": raise HTTPException(403,"Solo el trabajador asignado gestiona el resultado de la visita")
    if not o or o.asignado_a_usuario_id!=user.id:raise HTTPException(404,"Orden no encontrada")
    nuevo=data.get("estado");validas={"ASIGNADA":["EN_RUTA"],"EN_RUTA":["VISITADA_EXITOSA","VISITADA_FALLIDA"],"VISITADA_FALLIDA":["PENDIENTE"]}
    if nuevo not in validas.get(o.estado,[]):raise HTTPException(409,"Transición de estado no permitida")
    if nuevo in {"VISITADA_EXITOSA","VISITADA_FALLIDA"} and not str(data.get("observaciones","")).strip(): raise HTTPException(422,"Las observaciones de la visita son obligatorias")
    if nuevo=="PENDIENTE" and o.intentos>=3:raise HTTPException(409,"Se alcanzó el máximo de intentos")
    o.estado=nuevo;o.fecha_visita=func.current_timestamp() if nuevo.startswith("VISITADA") else None
    note=str(data.get("observaciones","")).strip()
    if nuevo in {"VISITADA_EXITOSA","VISITADA_FALLIDA"}:
        o.intentos+=1;o.resultado="LIBRO_RECUPERADO" if nuevo=="VISITADA_EXITOSA" else "NO_ENCONTRADO"
        prior=o.observaciones or ""
        report=f"Intento {o.intentos} · {'Libro recuperado' if nuevo=='VISITADA_EXITOSA' else 'No encontrado'}: {note}"
        o.observaciones=f"{prior}\n{report}".strip()
    elif nuevo=="PENDIENTE" and note:
        prior=o.observaciones or ""
        o.observaciones=f"{prior}\nSe solicita un nuevo intento: {note}".strip()
    db.commit();return {"mensaje":"Estado actualizado"}

@app.post("/prestamos/{prestamo_id}/multa/pagar")
def pagar_multa(prestamo_id:int,db:Session=Depends(get_db),user:Usuario=Depends(roles("DUENO"))):
    p=db.get(Prestamo,prestamo_id)
    if not p or p.multa_estado!="PENDIENTE":raise HTTPException(409,"No hay multa pendiente")
    p.multa_estado="PAGADA";p.fecha_pago=date.today();p.pago_registrado_por_usuario_id=user.id;db.commit();return {"mensaje":"Multa pagada","monto":str(p.multa_monto),"fecha_pago":p.fecha_pago.isoformat()}

@app.on_event("startup")
def seed_owner():
    db=next(get_db())
    try:
        defaults=[
            (os.getenv("OWNER_EMAIL","dueno@biblioteca.local").lower(),os.getenv("OWNER_PASSWORD","ChangeMe123!"),"Dueño","DUENO"),
            (os.getenv("LIBRARIAN_EMAIL","bibliotecario@biblioteca.local").lower(),os.getenv("LIBRARIAN_PASSWORD","Bibliotecario123!"),"Bibliotecario de muestra","BIBLIOTECARIO"),
            (os.getenv("FIELD_WORKER_EMAIL","reclamador@biblioteca.local").lower(),os.getenv("FIELD_WORKER_PASSWORD","Reclamador123!"),"Trabajador de campo de muestra","RECLAMADOR"),
        ]
        for email,password,nombre,rol in defaults:
            if not db.scalar(select(Usuario).where(Usuario.email==email)):
                db.add(Usuario(nombre=nombre,email=email,password_hash=hasher.hash(password),rol=rol,activo=True))
        db.commit()
        owner=db.scalar(select(Usuario).where(Usuario.rol=="DUENO").order_by(Usuario.id))
        worker=db.scalar(select(Usuario).where(Usuario.email==os.getenv("FIELD_WORKER_EMAIL","reclamador@biblioteca.local").lower()))
        if not db.scalar(select(Libro.id).where(Libro.codigo=="DEMO001")):
            db.add_all([
                Libro(codigo="DEMO001",titulo="Cien años de soledad",titulo_normalizado="cien anos de soledad",autor="Gabriel García Márquez",anio_impresion=1967,estado="DISPONIBLE",activo=True),
                Libro(codigo="DEMO002",titulo="El principito",titulo_normalizado="el principito",autor="Antoine de Saint-Exupéry",anio_impresion=1943,estado="DISPONIBLE",activo=True),
                Libro(codigo="DEMO003",titulo="La ciudad y los perros",titulo_normalizado="la ciudad y los perros",autor="Mario Vargas Llosa",anio_impresion=1963,estado="DISPONIBLE",activo=True),
            ]);db.flush()
        if not db.scalar(select(Lector.id).where(Lector.dni=="40000001")):
            db.add_all([
                Lector(dni="40000001",nombre="María Fernanda Ríos",direccion="Calle de los Libros 123",telefono="+51 900 100 001",activo=True),
                Lector(dni="40000002",nombre="Jorge Salazar Díaz",direccion="Av. La Lectura 456",telefono="+51 900 100 002",activo=True),
            ]);db.flush()
        demo_book=db.scalar(select(Libro).where(Libro.codigo=="DEMO001")); demo_book2=db.scalar(select(Libro).where(Libro.codigo=="DEMO002"))
        demo_reader=db.scalar(select(Lector).where(Lector.dni=="40000001")); demo_reader2=db.scalar(select(Lector).where(Lector.dni=="40000002"))
        if not db.scalar(select(Prestamo.id).where(Prestamo.libro_id==demo_book.id)):
            demo_book.estado="PRESTADO"; demo_book2.estado="PRESTADO"
            db.add_all([
                Prestamo(libro_id=demo_book.id,lector_id=demo_reader.id,fecha_prestamo=date.today(),fecha_vencimiento=date.today()+timedelta(days=7),estado="ACTIVO",dias_atraso=0,multa_monto=Decimal("0.00"),multa_estado="NO_APLICA",registrado_por_usuario_id=owner.id),
                Prestamo(libro_id=demo_book2.id,lector_id=demo_reader2.id,fecha_prestamo=date.today()-timedelta(days=10),fecha_vencimiento=date.today()-timedelta(days=3),estado="ACTIVO",dias_atraso=0,multa_monto=Decimal("0.00"),multa_estado="NO_APLICA",registrado_por_usuario_id=owner.id),
            ]);db.flush()
            overdue=db.scalar(select(Prestamo).where(Prestamo.libro_id==demo_book2.id,Prestamo.estado=="ACTIVO"))
            db.add(OrdenReclamo(prestamo_id=overdue.id,lector_id=demo_reader2.id,direccion_snapshot=demo_reader2.direccion,telefono_snapshot=demo_reader2.telefono,estado="ASIGNADA",asignado_a_usuario_id=worker.id,intentos=0))
        db.commit()
    finally: db.close()
