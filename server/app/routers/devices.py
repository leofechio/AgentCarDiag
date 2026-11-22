"""
routers/devices.py — Endpoints para Linha de Produção, Oficinas e Ativação de Equipamentos
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
import logging
from datetime import datetime, timezone

from app.database import get_db

logger = logging.getLogger("cardiag.devices.router")

router = APIRouter(prefix="/api/workshops", tags=["Workshops & Hardware Devices"])

# ─── Schemas ──────────────────────────────────────────────────────────────────

class WorkshopCreate(BaseModel):
    id: str
    name: str
    owner_name: Optional[str] = ""
    contact_email: Optional[str] = ""
    contact_phone: Optional[str] = ""
    username: Optional[str] = None
    password: Optional[str] = "123456"

class WorkshopUpdate(BaseModel):
    name: Optional[str] = None
    owner_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    status: Optional[str] = None

class DeviceProductionCreate(BaseModel):
    serial_number: Optional[str] = None
    device_type: str = "SCANNER_CAN" # 'SCANNER_CAN', 'AGUIACAR_4G', 'OSCILOSCOPIO'
    model_name: Optional[str] = "AgentCar Scanner Pro (TWAI + K-Line MUX)"
    batch_code: Optional[str] = "LOTE-2026-01"
    quantity: Optional[int] = 1

class DeviceClaimRequest(BaseModel):
    serial_number: str
    workshop_id: str

class DeviceAssignRequest(BaseModel):
    serial_number: str
    workshop_id: str

def _now():
    return datetime.now(timezone.utc).isoformat()

# ─── Endpoints Específicos de Equipamentos (Antes das rotas dinâmicas) ─────────

@router.get("/stock/devices", summary="Lista equipamentos em estoque fabril prontos para venda")
async def list_stock_devices():
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM hardware_devices WHERE status = 'IN_STOCK' ORDER BY serial_number ASC"
        ) as cur:
            rows = await cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in rows]

@router.get("/all-devices", summary="Lista todos os equipamentos fabricados e seus status")
async def list_all_devices():
    async with get_db() as db:
        async with db.execute("""
            SELECT h.*, w.name as workshop_name 
            FROM hardware_devices h
            LEFT JOIN workshops w ON h.workshop_id = w.id
            ORDER BY h.created_at DESC
        """) as cur:
            rows = await cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in rows]

@router.post("/devices/produce", summary="Linha de produção: gera um ou mais números de série no estoque")
async def produce_device(payload: DeviceProductionCreate):
    qty = max(1, min(payload.quantity or 1, 50))
    generated_serials = []
    
    # Letra indicadora do tipo de equipamento:
    # 's' = Scanner CAN (ex: s2001)
    # 'a' = AguiaCar 4G (ex: a2001)
    # 'o' = Osciloscópio (ex: o2001)
    letter = "s"
    if payload.device_type == "AGUIACAR_4G":
        letter = "a"
    elif payload.device_type == "OSCILOSCOPIO":
        letter = "o"

    async with get_db() as db:
        # Busca o maior número de série existente para essa letra para continuar a contagem sequencial
        async with db.execute(
            "SELECT serial_number FROM hardware_devices WHERE serial_number LIKE ? ORDER BY serial_number DESC",
            (f"{letter}%",)
        ) as cur:
            rows = await cur.fetchall()
            max_num = 2000
            for r in rows:
                s_str = r[0]
                num_part = ''.join(c for c in s_str if c.isdigit())
                if num_part:
                    try:
                        n = int(num_part)
                        if n > max_num:
                            max_num = n
                    except ValueError:
                        pass

        current_counter = max_num

        for i in range(qty):
            if payload.serial_number and qty == 1:
                clean_serial = payload.serial_number.strip().lower()
            else:
                current_counter += 1
                clean_serial = f"{letter}{current_counter}"

            try:
                await db.execute(
                    "INSERT INTO hardware_devices (serial_number, device_type, model_name, batch_code, status, created_at) VALUES (?,?,?,?,?,?)",
                    (clean_serial, payload.device_type, payload.model_name or "AgentCar Scanner Pro", payload.batch_code or "LOTE-2026-01", 'IN_STOCK', _now())
                )
                generated_serials.append(clean_serial)
            except Exception as e:
                logger.warning(f"Conflito ou erro ao gerar serial {clean_serial}: {e}")

        await db.commit()

        if not generated_serials:
            raise HTTPException(status_code=400, detail="Não foi possível gerar seriais. Verifique se já existem.")

        return {
            "status": "success", 
            "msg": f"Sucesso! {len(generated_serials)} equipamento(s) gerado(s) na Linha de Produção.",
            "serials": generated_serials
        }

@router.post("/devices/claim", summary="Oficina ativa/cadastra um aparelho pelo número de série")
async def claim_device(payload: DeviceClaimRequest):
    clean_serial = payload.serial_number.strip().lower()
    workshop_id = payload.workshop_id.strip().lower()

    async with get_db() as db:
        # 1. Verifica se a oficina existe
        async with db.execute("SELECT id, name FROM workshops WHERE id = ?", (workshop_id,)) as cur:
            w_row = await cur.fetchone()
            if not w_row:
                raise HTTPException(status_code=404, detail="Oficina não encontrada no sistema.")

        # 2. Busca o aparelho pelo Serial
        async with db.execute("SELECT serial_number, workshop_id, status FROM hardware_devices WHERE LOWER(serial_number) = ?", (clean_serial,)) as cur:
            dev_row = await cur.fetchone()
            if not dev_row:
                raise HTTPException(
                    status_code=404, 
                    detail=f"Número de série '{clean_serial}' não encontrado na base da fábrica."
                )

            real_serial = dev_row[0]
            current_workshop = dev_row[1]
            if current_workshop and current_workshop != workshop_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Este equipamento já está vinculado a outra oficina cadastrada."
                )

        # 3. Vincula o aparelho à oficina
        now_str = _now()
        await db.execute(
            "UPDATE hardware_devices SET workshop_id = ?, status = 'ACTIVE', activated_at = COALESCE(activated_at, ?) WHERE serial_number = ?",
            (workshop_id, now_str, real_serial)
        )
        await db.commit()

        logger.info(f"🔑 [HARDWARE ATIVADO] Serial: {real_serial} vinculado à oficina: {workshop_id}")
        return {
            "status": "success",
            "msg": f"Equipamento {real_serial} ativado e liberado com sucesso para {w_row[1]}!",
            "serial_number": real_serial,
            "workshop_id": workshop_id
        }

@router.post("/devices/assign", summary="Admin vincula diretamente um aparelho a uma oficina")
async def assign_device(payload: DeviceAssignRequest):
    clean_serial = payload.serial_number.strip().lower()
    workshop_id = payload.workshop_id.strip().lower()

    async with get_db() as db:
        async with db.execute("SELECT id, name FROM workshops WHERE id = ?", (workshop_id,)) as cur:
            w_row = await cur.fetchone()
            if not w_row:
                raise HTTPException(status_code=404, detail="Oficina não encontrada.")

        await db.execute(
            "UPDATE hardware_devices SET workshop_id = ?, status = 'ACTIVE', activated_at = COALESCE(activated_at, ?) WHERE LOWER(serial_number) = ?",
            (workshop_id, _now(), clean_serial)
        )
        await db.commit()
        return {"status": "success", "msg": f"Equipamento {clean_serial} vinculado com sucesso à oficina {w_row[1]}."}

@router.delete("/devices/{serial_number}/unlink", summary="Desvincula um equipamento de uma oficina (Retorno para estoque)")
async def unlink_device(serial_number: str):
    clean_serial = serial_number.strip().lower()
    async with get_db() as db:
        await db.execute(
            "UPDATE hardware_devices SET workshop_id = NULL, status = 'IN_STOCK' WHERE LOWER(serial_number) = ?",
            (clean_serial,)
        )
        await db.commit()
        return {"status": "success", "msg": f"Equipamento {clean_serial} retornado ao estoque fabril."}

@router.delete("/devices/{serial_number}", summary="Exclui definitivamente um serial de hardware")
async def delete_device(serial_number: str):
    clean_serial = serial_number.strip().lower()
    async with get_db() as db:
        await db.execute("DELETE FROM hardware_devices WHERE LOWER(serial_number) = ?", (clean_serial,))
        await db.commit()
        return {"status": "success", "msg": f"Equipamento {clean_serial} excluído do banco de dados."}


class DeviceProvisionRequest(BaseModel):
    device_type: str = "Scanner_CAN"
    token: Optional[str] = None
    require_confirmation: bool = True


class LegacyModeToggleRequest(BaseModel):
    enabled: bool
    force: bool = False


@router.post("/devices/{serial_number}/provision", summary="Provisiona credencial individual para um dispositivo ESP32")
async def provision_device_endpoint(serial_number: str, payload: DeviceProvisionRequest):
    from app import database as db_mod
    res = await db_mod.provision_device_credential(
        serial=serial_number,
        device_type=payload.device_type,
        token=payload.token,
        require_confirmation=payload.require_confirmation,
    )
    return {"status": "success", **res}


@router.post("/devices/{serial_number}/revoke", summary="Revoga imediatamente a credencial e encerra o socket ativo")
async def revoke_device_endpoint(serial_number: str):
    from app import database as db_mod
    from app.websocket_manager import gateway_manager
    revoked = await db_mod.revoke_device_credential(serial_number)
    evicted = await gateway_manager.evict_revoked_device(serial_number)
    return {
        "status": "revoked",
        "serial": serial_number.strip().lower(),
        "credential_found": revoked,
        "active_sockets_evicted": evicted,
    }


@router.get("/devices/credentials/status", summary="Consulta status de migração de credenciais individuais e modo legado")
async def get_credentials_migration_status():
    from app import database as db_mod
    return await db_mod.get_migration_status_summary()


@router.post("/devices/credentials/legacy-mode", summary="Controla ativação/desativação do modo legado WS_TOKEN")
async def toggle_legacy_mode_endpoint(payload: LegacyModeToggleRequest):
    from app import database as db_mod
    ok, reason = await db_mod.set_legacy_auth_enabled(payload.enabled, force=payload.force)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Não é permitido desativar o modo legado ainda: {reason}",
        )
    return {"status": "success", "legacy_ws_token_enabled": payload.enabled, "reason": reason}


# ─── Endpoints de Oficinas ───────────────────────────────────────────────────

@router.get("", summary="Lista todas as oficinas cadastradas")
async def list_workshops():
    async with get_db() as db:
        async with db.execute("SELECT * FROM workshops ORDER BY name ASC") as cur:
            rows = await cur.fetchall()
            cols = [c[0] for c in cur.description]
            workshops = [dict(zip(cols, r)) for r in rows]

            # Inclui contagem de aparelhos ativos por oficina
            for w in workshops:
                async with db.execute(
                    "SELECT COUNT(*) FROM hardware_devices WHERE workshop_id = ?",
                    (w["id"],)
                ) as dev_cur:
                    dev_row = await dev_cur.fetchone()
                    w["device_count"] = dev_row[0] if dev_row else 0

            return workshops

@router.post("", summary="Cadastra uma nova oficina / cliente com Login e Senha")
async def create_workshop(payload: WorkshopCreate):
    w_id = payload.id.strip().lower()
    w_name = payload.name.strip()
    w_user = (payload.username.strip() if payload.username else w_id)
    w_pass = (payload.password.strip() if payload.password else "123456")

    async with get_db() as db:
        try:
            await db.execute(
                """INSERT INTO workshops (id, name, owner_name, contact_email, contact_phone, username, password_hash, created_at, status)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (w_id, w_name, payload.owner_name or "", payload.contact_email or "", payload.contact_phone or "", w_user, w_pass, _now(), 'ACTIVE')
            )
            await db.commit()
            return {
                "status": "success", 
                "msg": f"Oficina '{w_name}' cadastrada com sucesso! Login: {w_user} / Senha: {w_pass}",
                "id": w_id,
                "username": w_user
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro ao criar oficina: {str(e)}")

@router.patch("/{workshop_id}", summary="Atualiza dados, status ou senha da oficina")
async def update_workshop(workshop_id: str, payload: WorkshopUpdate):
    w_id = workshop_id.strip().lower()
    async with get_db() as db:
        fields = []
        vals = []
        if payload.name is not None:
            fields.append("name = ?")
            vals.append(payload.name.strip())
        if payload.owner_name is not None:
            fields.append("owner_name = ?")
            vals.append(payload.owner_name.strip())
        if payload.contact_email is not None:
            fields.append("contact_email = ?")
            vals.append(payload.contact_email.strip())
        if payload.contact_phone is not None:
            fields.append("contact_phone = ?")
            vals.append(payload.contact_phone.strip())
        if payload.username is not None and payload.username.strip():
            fields.append("username = ?")
            vals.append(payload.username.strip())
        if payload.password is not None and payload.password.strip():
            fields.append("password_hash = ?")
            vals.append(payload.password.strip())
        if payload.status is not None:
            fields.append("status = ?")
            vals.append(payload.status.strip())

        if not fields:
            return {"status": "no_change"}

        vals.append(w_id)
        await db.execute(f"UPDATE workshops SET {', '.join(fields)} WHERE id = ?", tuple(vals))
        await db.commit()
        return {"status": "success", "msg": f"Oficina {w_id} atualizada com sucesso!"}

@router.delete("/{workshop_id}", summary="Exclui oficina e retorna aparelhos para estoque")
async def delete_workshop(workshop_id: str):
    w_id = workshop_id.strip().lower()
    async with get_db() as db:
        # Move aparelhos para o estoque fabril
        await db.execute("UPDATE hardware_devices SET workshop_id = NULL, status = 'IN_STOCK' WHERE workshop_id = ?", (w_id,))
        await db.execute("DELETE FROM workshops WHERE id = ?", (w_id,))
        await db.commit()
        return {"status": "success", "msg": f"Oficina {w_id} removida. Seus equipamentos retornaram ao estoque."}

@router.get("/{workshop_id}/devices", summary="Lista os equipamentos vinculados a uma oficina")
async def list_workshop_devices(workshop_id: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM hardware_devices WHERE workshop_id = ? ORDER BY created_at DESC",
            (workshop_id.strip().lower(),)
        ) as cur:
            rows = await cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in rows]

