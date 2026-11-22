#!/usr/bin/env python3
"""
hantek1008_driver.py — Driver USB Multi-Plataforma (Linux & Windows) para Osciloscópio Automotivo Hantek 1008C
USB VID: 0x0783 | PID: 0x5725 (YDJ-2088 / Hantek 1008C 8-Channel Automotive Oscilloscope)
Projeto AgentCarDiag

Suporta:
  - Autocalibração dinâmica de Zero Offset por canal e por escala vertical (1.0, 0.125, 0.02 V/div)
    sem assertions rígidas de EEPROM de fábrica (compatível com todas as revisões de hardware Hantek 1008C/1008B/1008A).
  - Captura Burst (2.000 amostras por canal ativo) e Modo Roll Contínuo (streaming em tempo real).
  - Cálculo de métricas automotivas (Vmin, Vmax, Vmean, Vpp, Vrms, Duty Cycle % e Frequência Hz).
  - Gerador de Formas de Onda Digital de 8 Canais integrado.
"""

from __future__ import annotations

import copy
import logging
import math
import time
from time import sleep
from typing import Dict, Generator, List, Optional, Tuple, Union

import usb.core
import usb.util

logger = logging.getLogger("cardiag.hantek1008")

HANTEK_VID = 0x0783
HANTEK_PID = 0x5725


class Hantek1008C:
    """
    Driver USB direto (PyUSB / libusb) para o Osciloscópio Automotivo Hantek 1008C (8 Canais).
    """

    MAX_PACKAGE_SIZE: int = 64
    VSCALE_FACTORS: List[float] = [0.02, 0.125, 1.0]
    ROLL_RATES_MAP: Dict[float, int] = {
        440: 0x18,
        220: 0x19,
        88: 0x1A,
        44: 0x1B,
        22: 0x1C,
        11: 0x1D,
        5: 0x1E,
        2: 0x1F,
        1: 0x20,
        0.5: 0x21,
        0.25: 0x22,
        0.125: 0x23,
        1.0 / 16: 0x24,
    }
    BURST_NS_PER_DIV_MAP: Dict[int, int] = {
        ({0: 1, 1: 2, 2: 5}[idx % 3] * (10 ** (idx // 3))): idx for idx in range(26)
    }

    def __init__(
        self,
        ns_per_div: int = 500_000,
        vertical_scale_factor: Union[float, List[float]] = 1.0,
        active_channels: Optional[List[int]] = None,
        trigger_channel: int = 0,
        trigger_slope: str = "rising",
        trigger_level: int = 2048,
        probe_attenuation: Union[float, List[float]] = 1.0,
    ) -> None:
        self.ns_per_div = ns_per_div if ns_per_div in self.BURST_NS_PER_DIV_MAP else 500_000
        self.active_channels = sorted(active_channels if active_channels is not None else list(range(8)))
        if isinstance(vertical_scale_factor, (int, float)):
            v_val = float(vertical_scale_factor)
            if v_val not in self.VSCALE_FACTORS:
                v_val = 1.0
            self.vertical_scale_factors = [v_val] * 8
        else:
            self.vertical_scale_factors = list(vertical_scale_factor)

        if isinstance(probe_attenuation, (int, float)):
            self.probe_attenuations = [float(probe_attenuation)] * 8
        else:
            self.probe_attenuations = list(probe_attenuation)

        self.trigger_channel = trigger_channel
        self.trigger_slope = trigger_slope
        self.trigger_level = trigger_level

        self.zero_offsets: Dict[float, List[float]] = {}
        self.eeprom_calibration: Dict[str, str] = {}

        self._dev: Optional[usb.core.Device] = None
        self._cfg: Optional[usb.core.Configuration] = None
        self._intf: Optional[usb.core.Interface] = None
        self._ep_out: Optional[usb.core.Endpoint] = None
        self._ep_in: Optional[usb.core.Endpoint] = None

    @staticmethod
    def is_connected() -> bool:
        """Verifica rapidamente se o Hantek 1008C (0783:5725) está plugado no barramento USB."""
        return usb.core.find(idVendor=HANTEK_VID, idProduct=HANTEK_PID) is not None

    def connect(self) -> None:
        """Localiza o Hantek 1008C via USB e reivindica os endpoints Bulk OUT (0x02) e IN (0x81)."""
        self._dev = usb.core.find(idVendor=HANTEK_VID, idProduct=HANTEK_PID)
        if self._dev is None:
            raise RuntimeError(
                "Hantek 1008C (USB 0783:5725 / YDJ-2088) não encontrado. "
                "Verifique o cabo USB (no Linux: regra udev /etc/udev/rules.d/99-hantek1008.rules; "
                "no Windows: driver WinUSB/libusb via Zadig para YDJ-2088)."
            )

        try:
            if self._dev.is_kernel_driver_active(0):
                self._dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass

        self._dev.set_configuration()
        self._cfg = self._dev.get_active_configuration()
        self._intf = self._cfg[(0, 0)]

        self._ep_out = usb.util.find_descriptor(
            self._intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
        )
        self._ep_in = usb.util.find_descriptor(
            self._intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN,
        )
        if self._ep_out is None or self._ep_in is None:
            raise RuntimeError("Não foi possível localizar os endpoints USB IN/OUT do Hantek 1008C.")

        self._clear_leftover()

    def _clear_leftover(self) -> None:
        if self._ep_in is None:
            return
        try:
            self._ep_in.read(64, timeout=80)
        except usb.core.USBError:
            pass

    def _write_and_receive(
        self,
        message: bytes,
        response_length: int,
        sec_till_response_request: float = 0.002,
        sec_till_start: float = 0.002,
    ) -> bytes:
        if self._ep_out is None or self._ep_in is None:
            raise RuntimeError("Dispositivo USB não conectado.")
        sleep(sec_till_start)
        self._ep_out.write(message)
        sleep(sec_till_response_request)
        resp = bytes(self._ep_in.read(response_length, timeout=2000))
        return resp

    def _send_cmd(
        self,
        cmd_id: int,
        parameter: Union[bytes, List[int], str] = b"",
        response_length: int = 0,
        echo_expected: bool = True,
        sec_till_response_request: float = 0.0,
        sec_till_start: float = 0.002,
    ) -> bytes:
        if isinstance(parameter, str):
            parameter = bytes.fromhex(parameter)
        elif isinstance(parameter, list):
            parameter = bytes(parameter)
        msg = bytes([cmd_id]) + parameter
        total_len = response_length + (1 if echo_expected else 0)
        resp = self._write_and_receive(
            msg,
            total_len,
            sec_till_response_request=sec_till_response_request,
            sec_till_start=sec_till_start,
        )
        if echo_expected:
            if len(resp) == 0 or resp[0] != cmd_id:
                raise RuntimeError(f"Eco inválido do Hantek 1008C para cmd 0x{cmd_id:02X}: {resp.hex()}")
            return resp[1:]
        return resp

    def _send_ping(self, sec_till_start: float = 0.0) -> None:
        self._send_cmd(0xF3, sec_till_start=sec_till_start)

    def _send_a55a(self, attempts: int = 25) -> None:
        for _ in range(attempts):
            resp = self._send_cmd(0xA5, parameter=[0x5A], response_length=1)
            if resp and resp[0] in (2, 3):
                return
            sleep(0.02)
            self._send_ping()
        raise RuntimeError("Timeout aguardando buffer de captura do Hantek 1008C (comando A5 5A).")

    def _send_c6_a6(self, parameter: int) -> bytes:
        resp = self._send_cmd(0xC6, parameter=[parameter], response_length=2, echo_expected=False)
        sample_length = int.from_bytes(resp, byteorder="big", signed=False)
        packages = int(math.ceil(sample_length / self.MAX_PACKAGE_SIZE))
        samples = bytearray()
        for _ in range(packages):
            chunk = self._send_cmd(0xA6, parameter=[parameter], response_length=64, echo_expected=False)
            samples.extend(chunk)
        return bytes(samples[:sample_length])

    def _send_set_time_div(self, ns_per_div: int) -> None:
        t_id = self.BURST_NS_PER_DIV_MAP.get(ns_per_div, self.BURST_NS_PER_DIV_MAP[500_000])
        self._send_cmd(0xA3, parameter=[t_id])

    def _send_set_vertical_scale(self, scale_factors: List[float]) -> None:
        ids = [self.VSCALE_FACTORS.index(sf) + 1 for sf in scale_factors]
        self._send_cmd(0xA2, parameter=ids, sec_till_response_request=0.2132)

    def _send_set_active_channels(self, active_channels: List[int]) -> None:
        self._send_cmd(0xA0, parameter=[len(active_channels)])
        bmap = [0x01 if i in active_channels else 0x00 for i in range(8)]
        self._send_cmd(0xAA, parameter=bmap)

    def _send_set_trigger(self, source_channel: int, slope: str) -> None:
        slope_id = 0 if slope.lower() in ("rising", "rise") else 1
        self._send_cmd(0xC1, parameter=[source_channel, slope_id])

    def _send_set_trigger_level(self, level: int) -> None:
        lvl = max(0, min(4095, int(level)))
        self._send_cmd(0xAB, parameter=lvl.to_bytes(2, byteorder="big", signed=False))

    def set_generator(self, turn_on: bool = False, speed_rpm: int = 300_000) -> None:
        pulse_len = int(((8 * 360_000_000) / 8) / max(1, min(750_000, speed_rpm)))
        param = b"\x01" + pulse_len.to_bytes(4, byteorder="little", signed=False)
        self._send_cmd(0xB9, parameter=param)
        self._send_cmd(0xB7, parameter=[0x00])
        self._send_cmd(0xBB, parameter=[0x08, 0x01 if turn_on else 0x00])

    def init(self, calibrate_all_scales: bool = True) -> None:
        """
        Inicializa o Hantek 1008C e calibra o zero offset real de cada um dos 8 canais
        executando a sequência completa das 3 escalas (0.02, 0.125, 1.0) exigida pelo firmware STM32.
        """
        # Etapa 1: Handshake e leitura de constantes da EEPROM individual do aparelho
        self._send_cmd(0xB0)
        sleep(0.35)
        self._send_cmd(0xB0)
        self._send_ping()

        self.set_generator(turn_on=False, speed_rpm=300_000)

        self.eeprom_calibration["b5"] = self._send_cmd(
            0xB5, response_length=64, echo_expected=False, sec_till_response_request=0.0193
        ).hex()
        self.eeprom_calibration["b6"] = self._send_cmd(0xB6, response_length=64, echo_expected=False).hex()
        self.eeprom_calibration["e5"] = self._send_cmd(0xE5, response_length=2, echo_expected=False).hex()
        self.eeprom_calibration["f7"] = self._send_cmd(0xF7, response_length=64, echo_expected=False).hex()
        self.eeprom_calibration["f8"] = self._send_cmd(0xF8, response_length=64, echo_expected=False).hex()
        self.eeprom_calibration["fa"] = self._send_cmd(0xFA, response_length=56, echo_expected=False).hex()

        self._send_cmd(0xF5, sec_till_response_request=0.2132)
        self._send_set_active_channels(list(range(8)))
        self._send_set_time_div(500_000)
        self._send_set_trigger(0, "rising")
        self._send_cmd(0xA7, parameter=bytes.fromhex("0000"), response_length=1)
        self._send_cmd(0xAC, parameter=bytes.fromhex("01f40009c50009c5"))

        # Etapa 2: Calibração de Zero Offset (DAC Zero Reference) dos 8 canais
        self.zero_offsets = {}
        scales_to_measure = self.VSCALE_FACTORS if calibrate_all_scales else [1.0]
        for vscale in scales_to_measure:
            self._send_ping()
            self._send_set_vertical_scale([vscale] * 8)
            self._send_cmd(0xA4, parameter=[0x01])
            self._send_cmd(0xC0)
            sleep(0.0124)
            self._send_cmd(0xC2)
            self._send_a55a()
            raw_bytes = self._send_c6_a6(0x02) + self._send_c6_a6(0x03)
            shorts = self._bytes_to_shorts(raw_bytes)
            per_ch = self._split_channels(shorts, list(range(8)))
            self.zero_offsets[vscale] = [sum(per_ch[ch]) / float(len(per_ch[ch])) for ch in range(8)]

        if not calibrate_all_scales:
            base_zo = self.zero_offsets[1.0]
            for vscale in self.VSCALE_FACTORS:
                if vscale not in self.zero_offsets:
                    self.zero_offsets[vscale] = list(base_zo)

        # Etapa 3: Configuração de aquisição ativa
        self._send_cmd(0xF6, sec_till_response_request=0.2132)
        self._send_cmd(0xE5, echo_expected=False, response_length=2)
        self._send_cmd(0xF7, echo_expected=False, response_length=64)
        self._send_cmd(0xF8, echo_expected=False, response_length=64)
        self._send_cmd(0xFA, echo_expected=False, response_length=56)

        self._send_set_time_div(self.ns_per_div)
        self._send_cmd(0xAC, parameter=bytes.fromhex("00c80002bd0002bd"))
        self._send_cmd(0xE4, parameter=[0x01])
        self._send_cmd(0xE6, parameter=[0x01], echo_expected=False, response_length=10)
        self._send_ping()

        self._send_set_active_channels(self.active_channels)
        self._send_set_vertical_scale(self.vertical_scale_factors)
        self._send_set_time_div(self.ns_per_div)
        self._send_set_trigger(self.trigger_channel, self.trigger_slope)
        self._send_cmd(0xA7, parameter=[0x00, 0x00], response_length=1)
        self._send_cmd(0xAC, parameter=bytes.fromhex("0000000001000579"))
        self._send_set_trigger_level(self.trigger_level)
        self._send_cmd(0xE9, echo_expected=False, response_length=2)

    @staticmethod
    def _bytes_to_shorts(data: bytes) -> List[int]:
        n = len(data) - (len(data) % 2)
        return [data[i] + (data[i + 1] << 8) for i in range(0, n, 2)]

    @staticmethod
    def _split_channels(
        shorts: List[int], active_channels: List[int], expect_ninth_channel: bool = False
    ) -> Dict[int, List[int]]:
        ch_sorted = sorted(active_channels)
        stride = len(ch_sorted) + (1 if expect_ninth_channel else 0)
        return {ch_sorted[i]: shorts[i::stride] for i in range(len(ch_sorted))}

    def _raw_to_volts(self, raw_values: List[int], channel_id: int) -> List[float]:
        vscale = self.vertical_scale_factors[channel_id]
        atten = self.probe_attenuations[channel_id]
        zero_offset = self.zero_offsets.get(vscale, [2020.0] * 8)[channel_id]
        scale = 0.01 * vscale * atten
        return [round((v - zero_offset) * scale, 4) for v in raw_values]

    def capture_burst(self, as_volts: bool = True) -> Dict[int, Union[List[float], List[int]]]:
        """Captura uma janela completa de alta velocidade (2.000 amostras por canal ativo)."""
        self._send_ping()
        self._send_cmd(0xE4, parameter=[0x01])
        self._send_cmd(0xE6, parameter=[0x01], echo_expected=False, response_length=10)
        self._send_cmd(0xA4, parameter=[0x01], sec_till_response_request=0.015)
        self._send_cmd(0xC0)
        self._send_cmd(0xC2)
        self._send_a55a()

        raw_bytes = self._send_c6_a6(0x02) + self._send_c6_a6(0x03)
        self._send_cmd(0xE4, parameter=[0x01])
        self._send_cmd(0xE6, parameter=[0x01], echo_expected=False, response_length=10)

        shorts = self._bytes_to_shorts(raw_bytes)
        per_ch = self._split_channels(shorts, self.active_channels)
        if not as_volts:
            return per_ch
        return {ch: self._raw_to_volts(vals, ch) for ch, vals in per_ch.items()}

    def stream_roll_mode(
        self, sampling_rate: float = 440, as_volts: bool = True
    ) -> Generator[Dict[int, Union[List[float], List[int]]], None, None]:
        """Gerador contínuo em Roll Mode para sinais lentos (sensores Lambda, MAP, temperatura, etc.)."""
        rate_id = self.ROLL_RATES_MAP.get(sampling_rate, 0x18)
        self._send_cmd(0xA3, parameter=[rate_id])
        self._send_ping(sec_till_start=0.010)
        self._send_cmd(0xA4, parameter=[0x02])
        self._send_cmd(0xC0)
        self._send_cmd(0xC2)

        while True:
            ready_len = 0
            while ready_len == 0:
                self._send_ping()
                resp = self._send_cmd(0xC7, response_length=2, echo_expected=False)
                ready_len = int.from_bytes(resp, byteorder="big", signed=False)
            buf = bytearray()
            rem = ready_len
            while rem > 0:
                part = self._send_cmd(0xC8, response_length=64, echo_expected=False)
                if rem < 64:
                    part = part[:rem]
                rem -= 64
                buf.extend(part)
            shorts = self._bytes_to_shorts(bytes(buf))
            per_ch = self._split_channels(shorts, self.active_channels, expect_ninth_channel=True)
            if as_volts:
                yield {ch: self._raw_to_volts(vals, ch) for ch, vals in per_ch.items()}
            else:
                yield per_ch

    @staticmethod
    def compute_channel_metrics(samples: List[float], sample_rate_hz: float) -> Dict[str, float]:
        """Calcula métricas elétricas automotivas (Vmin, Vmax, Vmean, Vpp, Vrms, Duty %, Freq Hz)."""
        if not samples:
            return {"vmin": 0.0, "vmax": 0.0, "vmean": 0.0, "vpp": 0.0, "vrms": 0.0, "duty_pct": 0.0, "freq_hz": 0.0}
        n = len(samples)
        vmin = min(samples)
        vmax = max(samples)
        vmean = sum(samples) / n
        vpp = vmax - vmin
        vrms = math.sqrt(sum(v * v for v in samples) / n)

        mid = (vmax + vmin) / 2.0
        high_count = sum(1 for v in samples if v > mid)
        duty_pct = (high_count * 100.0 / n) if vpp > 0.05 else 0.0

        # Cruzamentos ascendentes pelo nível médio com histerese
        hyst = max(0.02, vpp * 0.1)
        crossings: List[float] = []
        armed = samples[0] < (mid - hyst)
        for i in range(1, n):
            if not armed and samples[i] < (mid - hyst):
                armed = True
            elif armed and samples[i] >= (mid + hyst):
                armed = False
                dv = samples[i] - samples[i - 1]
                frac = ((mid - samples[i - 1]) / dv) if abs(dv) > 1e-6 else 0.0
                crossings.append((i - 1) + max(0.0, min(1.0, frac)))

        freq_hz = 0.0
        if len(crossings) >= 2 and sample_rate_hz > 0:
            avg_period_samples = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
            if avg_period_samples > 0:
                freq_hz = sample_rate_hz / avg_period_samples

        return {
            "vmin": round(vmin, 3),
            "vmax": round(vmax, 3),
            "vmean": round(vmean, 3),
            "vpp": round(vpp, 3),
            "vrms": round(vrms, 3),
            "duty_pct": round(duty_pct, 1),
            "freq_hz": round(freq_hz, 2),
        }

    def get_effective_sample_rate_hz(self) -> float:
        """Calcula a taxa de amostragem efetiva em Burst Mode (~25 amostras por divisão)."""
        sec_per_div = self.ns_per_div * 1e-9
        if sec_per_div <= 0:
            return 50_000.0
        return round(25.0 / sec_per_div, 1)

    def close(self) -> None:
        if self._dev is None:
            return
        try:
            self._clear_leftover()
            self._send_ping()
            self._send_cmd(0xF4)
            self._dev.reset()
        except Exception:
            pass
        finally:
            self._dev = None
