#!python
from typing import Dict
import logging
import serial
import construct
import socket
import time 
from pathlib import Path
import sys

from HaMqttDevice import *

from options import OPT, SS_TOPIC


logger = logging.getLogger(__name__)

class HexToByte(construct.Adapter):
    def _decode(self, obj, context, path) -> bytes:
        hexstr = ''.join([chr(x) for x in obj])
        return bytes.fromhex(hexstr)


class JoinBytes(construct.Adapter):
    def _decode(self, obj, context, path) -> bytes:
        return ''.join([chr(x) for x in obj]).encode()


class DivideBy1000(construct.Adapter):
    def _decode(self, obj, context, path) -> float:
        return obj / 1000


class DivideBy100(construct.Adapter):
    def _decode(self, obj, context, path) -> float:
        return obj / 100


class ToVolt(construct.Adapter):
    def _decode(self, obj, context, path) -> float:
        return obj / 1000

class ToAmp(construct.Adapter):
    def _decode(self, obj, context, path) -> float:
        return obj / 10

class ToCelsius(construct.Adapter):
    def _decode(self, obj, context, path) -> float:
        return (obj - 2731) / 10.0  # in Kelvin*10



class Pylontech:
    manufacturer_info_fmt = construct.Struct(
        "DeviceName" / JoinBytes(construct.Array(10, construct.Byte)),
        "SoftwareVersion" / construct.Array(2, construct.Byte),
        "ManufacturerName" / JoinBytes(construct.GreedyRange(construct.Byte)),
    )

    system_parameters_fmt = construct.Struct(
        "CellHighVoltageLimit" / ToVolt(construct.Int16ub),
        "CellLowVoltageLimit" / ToVolt(construct.Int16ub),
        "CellUnderVoltageLimit" / ToVolt(construct.Int16sb),
        "ChargeHighTemperatureLimit" / ToCelsius(construct.Int16sb),
        "ChargeLowTemperatureLimit" / ToCelsius(construct.Int16sb),
        "ChargeCurrentLimit" / DivideBy100(construct.Int16sb),
        "ModuleHighVoltageLimit" / ToVolt(construct.Int16ub),
        "ModuleLowVoltageLimit" / ToVolt(construct.Int16ub),
        "ModuleUnderVoltageLimit" / ToVolt(construct.Int16ub),
        "DischargeHighTemperatureLimit" / ToCelsius(construct.Int16sb),
        "DischargeLowTemperatureLimit" / ToCelsius(construct.Int16sb),
        "DischargeCurrentLimit" / DivideBy100(construct.Int16sb),
    )

    management_info_fmt = construct.Struct(
        "CommandValue" / construct.Byte,
        "ChargeVoltageLimit" / ToVolt(construct.Int16ub),
        "DischargeVoltageLimit" / ToVolt(construct.Int16ub),
        "ChargeCurrentLimit" / ToAmp(construct.Int16sb),
        "DishargeCurrentLimit" / ToAmp(construct.Int16sb),
        "Status" / construct.Byte,
    )

    module_serial_number_fmt = construct.Struct(
        "CommandValue" / construct.Byte,
        "ModuleSerialNumber" / JoinBytes(construct.Array(16, construct.Byte)),
    )


    get_values_fmt = construct.Struct(
        "NumberOfModules" / construct.Byte,
        "Module" / construct.Array(construct.this.NumberOfModules, construct.Struct(
            "NumberOfCells" / construct.Int8ub,
            "CellVoltages" / construct.Array(construct.this.NumberOfCells, ToVolt(construct.Int16sb)),
            "NumberOfTemperatures" / construct.Int8ub,
            "AverageBMSTemperature" / ToCelsius(construct.Int16sb),
            "GroupedCellsTemperatures" / construct.Array(construct.this.NumberOfTemperatures - 1, ToCelsius(construct.Int16sb)),
            "Current" / ToAmp(construct.Int16sb),
            "Voltage" / ToVolt(construct.Int16ub),
            "Power" / construct.Computed(construct.this.Current * construct.this.Voltage),
            "_RemainingCapacity1" / DivideBy1000(construct.Int16ub),
            "_UserDefinedItems" / construct.Int8ub,
            "_TotalCapacity1" / DivideBy1000(construct.Int16ub),
            "CycleNumber" / construct.Int16ub,
            "_OptionalFields" / construct.If(construct.this._UserDefinedItems > 2,
                                           construct.Struct("RemainingCapacity2" / DivideBy1000(construct.Int24ub),
                                                            "TotalCapacity2" / DivideBy1000(construct.Int24ub))),
            "RemainingCapacity" / construct.Computed(lambda this: this._OptionalFields.RemainingCapacity2 if this._UserDefinedItems > 2 else this._RemainingCapacity1),
            "TotalCapacity" / construct.Computed(lambda this: this._OptionalFields.TotalCapacity2 if this._UserDefinedItems > 2 else this._TotalCapacity1),
        )),
        "TotalPower" / construct.Computed(lambda this: sum([x.Power for x in this.Module])),
        "StateOfCharge" / construct.Computed(lambda this: sum([x.RemainingCapacity for x in this.Module]) / sum([x.TotalCapacity for x in this.Module])),

    )
    get_values_single_fmt = construct.Struct(
        "NumberOfModule" / construct.Byte,
        "NumberOfCells" / construct.Int8ub,
        "CellVoltages" / construct.Array(construct.this.NumberOfCells, ToVolt(construct.Int16sb)),
        "NumberOfTemperatures" / construct.Int8ub,
        "AverageBMSTemperature" / ToCelsius(construct.Int16sb),
        "GroupedCellsTemperatures" / construct.Array(construct.this.NumberOfTemperatures - 1, ToCelsius(construct.Int16sb)),
        "Current" / ToAmp(construct.Int16sb),
        "Voltage" / ToVolt(construct.Int16ub),
        "Power" / construct.Computed(construct.this.Current * construct.this.Voltage),
        "_RemainingCapacity1" / DivideBy1000(construct.Int16ub),
        "_UserDefinedItems" / construct.Int8ub,
        "_TotalCapacity1" / DivideBy1000(construct.Int16ub),
        "CycleNumber" / construct.Int16ub,
        "_OptionalFields" / construct.If(construct.this._UserDefinedItems > 2,
                                       construct.Struct("RemainingCapacity2" / DivideBy1000(construct.Int24ub),
                                                        "TotalCapacity2" / DivideBy1000(construct.Int24ub))),
        "RemainingCapacity" / construct.Computed(lambda this: this._OptionalFields.RemainingCapacity2 if this._UserDefinedItems > 2 else this._RemainingCapacity1),
        "TotalCapacity" / construct.Computed(lambda this: this._OptionalFields.TotalCapacity2 if this._UserDefinedItems > 2 else this._TotalCapacity1),
        "TotalPower" / construct.Computed(construct.this.Power),
        "StateOfCharge" / construct.Computed(construct.this.RemainingCapacity / construct.this.TotalCapacity),
    )

    def __init__(self, serial_port='/dev/ttyUSB0', baudrate=115200, port_type='serial',tcp_host='0.0.0.0',tcp_port=502):
        self.port_type=port_type
        if (self.port_type == 'serial'):
            self.s = serial.Serial(serial_port, baudrate, bytesize=8, parity=serial.PARITY_NONE, stopbits=1, timeout=2)
        if (self.port_type == 'tcp'):
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.connect((tcp_host,tcp_port))



    @staticmethod
    def get_frame_checksum(frame: bytes):
        assert isinstance(frame, bytes)

        sum = 0
        for byte in frame:
            sum += byte
        sum = ~sum
        sum %= 0x10000
        sum += 1
        return sum

    @staticmethod
    def get_info_length(info: bytes) -> int:
        lenid = len(info)
        if lenid == 0:
            return 0

        lenid_sum = (lenid & 0xf) + ((lenid >> 4) & 0xf) + ((lenid >> 8) & 0xf)
        lenid_modulo = lenid_sum % 16
        lenid_invert_plus_one = 0b1111 - lenid_modulo + 1

        return (lenid_invert_plus_one << 12) + lenid


    def send_cmd(self, address: int, cmd, info: bytes = b''):
        raw_frame = self._encode_cmd(address, cmd, info)
        
        if OPT.debug > 0:
            print(raw_frame)
        
        if (self.port_type == 'serial'):
            self.s.write(raw_frame)
        if (self.port_type == 'tcp'):
            self.s.sendall(raw_frame)


    def _encode_cmd(self, address: int, cid2: int, info: bytes = b''):
        cid1 = 0x46

        info_length = Pylontech.get_info_length(info)

        frame = "{:02X}{:02X}{:02X}{:02X}{:04X}".format(0x20, address, cid1, cid2, info_length).encode()
        frame += info

        frame_chksum = Pylontech.get_frame_checksum(frame)
        whole_frame = (b"~" + frame + "{:04X}".format(frame_chksum).encode() + b"\r")
        return whole_frame


    def _decode_hw_frame(self, raw_frame: bytes) -> bytes:
        # XXX construct
        frame_data = raw_frame[1:len(raw_frame) - 5]
        frame_chksum = raw_frame[len(raw_frame) - 5:-1]

        got_frame_checksum = Pylontech.get_frame_checksum(frame_data)
        assert got_frame_checksum == int(frame_chksum, 16)

        return frame_data

    def _decode_frame(self, frame):
        format = construct.Struct(
            "ver" / HexToByte(construct.Array(2, construct.Byte)),
            "adr" / HexToByte(construct.Array(2, construct.Byte)),
            "cid1" / HexToByte(construct.Array(2, construct.Byte)),
            "cid2" / HexToByte(construct.Array(2, construct.Byte)),
            "infolength" / HexToByte(construct.Array(4, construct.Byte)),
            "info" / HexToByte(construct.GreedyRange(construct.Byte)),
        )

        return format.parse(frame)


    def read_frame(self):
        if (self.port_type == 'serial'):
            raw_frame = self.s.readline()
        if (self.port_type == 'tcp'):
            line = bytearray()
            cnt = 0
            while True:
                self.s.settimeout(0.1)
                try:
                    c = self.s.recv(1)
                    cnt= cnt+1
                except socket.timeout:
                    break
                if c:
                    line.extend(c)
                    #if c[0] == 0x0D:
                    #    break
                else:
                    break
            #print ("count: ", cnt)
            raw_frame=bytes(line)

        if OPT.debug > 0:
            print (raw_frame)
        if (cnt == 0):
            return 
        f = self._decode_hw_frame(raw_frame=raw_frame)
        parsed = self._decode_frame(f)
        return parsed

    def clear_buffer(self):
        if (self.port_type == 'serial'):
            raw_frame = self.s.readline()
        if (self.port_type == 'tcp'):
            line = bytearray()
            cnt = 0
            while True:
                self.s.settimeout(0.5)
                try:
                    c = self.s.recv(1)
                    cnt= cnt+1
                except socket.timeout:
                    break
                if c:
                    line.extend(c)
                else:
                    break

        return 

    def scan_for_batteries(self, start=0, end=10) -> Dict[int, str]:
        """ Returns a map of the batteries id to their serial number """
        batteries = {}
        for adr in range(start, end, 1):
            bdevid = "{:02X}".format(adr).encode()
            self.send_cmd(adr, 0x93, bdevid) # Probe for serial number
            #raw_frame = self.s.readline()
            raw_frame = self.read_frame()

            if raw_frame:
                sn = self.get_module_serial_number(adr)
                sn_str = sn["ModuleSerialNumber"].decode()

                batteries[adr] = sn_str
                print("Found battery at address " + str(adr) + " with serial " + sn_str)
            else:
                logger.debug("No battery found at address " + str(adr))

        return batteries


    def get_protocol_version(self,dev_id=2):
        self.send_cmd(dev_id, 0x4f)
        return self.read_frame()


    def get_manufacturer_info(self,dev_id=2):
        self.send_cmd(dev_id, 0x51)
        f = self.read_frame()
        return self.manufacturer_info_fmt.parse(f.info)


    def get_system_parameters(self, dev_id=None):
        if dev_id:
            bdevid = "{:02X}".format(dev_id).encode()
            self.send_cmd(dev_id, 0x47, bdevid)
        else:
            self.send_cmd(2, 0x47)

        f = self.read_frame()
        return self.system_parameters_fmt.parse(f.info[1:])

    def get_management_info(self,dev_id=2):
        #raise Exception('Dont touch this for now')
        if dev_id:
            bdevid = "{:02X}".format(dev_id).encode()
            self.send_cmd(dev_id, 0x92, bdevid)
        else:
            self.send_cmd(2, 0x92)
        f = self.read_frame()

        return self.management_info_fmt.parse(f.info)

    def get_module_serial_number(self, dev_id=None):
        if dev_id:
            bdevid = "{:02X}".format(dev_id).encode()
            self.send_cmd(dev_id, 0x93, bdevid)
        else:
            self.send_cmd(2, 0x93)

        f = self.read_frame()
        # infoflag = f.info[0]
        return self.module_serial_number_fmt.parse(f.info[0:])

    def get_values(self,dev_id=2):
        self.send_cmd(dev_id, 0x42, b'FF')
        f = self.read_frame()

        # infoflag = f.info[0]
        d = self.get_values_fmt.parse(f.info[1:])
        return d

    def get_values_single(self, dev_id):
        bdevid = "{:02X}".format(dev_id).encode()
        self.send_cmd(dev_id, 0x42, bdevid)
        f = self.read_frame()
        # infoflag = f.info[0]
        d = self.get_values_single_fmt.parse(f.info[1:])
        return d

def startup() -> None:
    """Read the hassos configuration."""
    logging.basicConfig(
        format="%(asctime)s %(levelname)-7s %(message)s", level=logging.DEBUG
    )

    hassosf = Path("/data/options.json")
    if hassosf.exists():
        logger.info("Loading HASS OS configuration")
        OPT.update(loads(hassosf.read_text(encoding="utf-8")))
    else:
        logger.info(
            "Local test mode - Defaults apply. Pass MQTT host & password as arguments"
        )
        configf = Path(__file__).parent / "config.yaml"
        OPT.update(yaml.safe_load(configf.read_text()).get("options", {}))
        #OPT.debug = 1

    #MQTT.availability_topic = f"{SS_TOPIC}/{OPT.pylontech_id}/availability"


    if OPT.debug < 2:
        logging.basicConfig(
            format="%(asctime)s %(levelname)-7s %(message)s",
            level=logging.INFO,
            force=True,
        )


if __name__ == '__main__':
    startup()
    print(OPT)

#    mqtt_client = mqtt.Client(callback_api_version= mqtt.CallbackAPIVersion.VERSION1, client_id = "pylontech")
    mqtt_client = mqtt.Client( client_id = "pylontech")
    mqtt_client.username_pw_set(OPT.mqtt_username, OPT.mqtt_password)
    mqtt_client.connect(OPT.mqtt_host, int(OPT.mqtt_port), 60)
    mqtt_client.loop_start()

    p = Pylontech(port_type='tcp',tcp_host=OPT.host,tcp_port=int(OPT.port))


    batts = {}

    p.clear_buffer()


    for x in range(1, OPT.max_batt):
      try:
        serial_numberx = p.get_module_serial_number(x).ModuleSerialNumber.decode("utf-8")
        manuf_info=p.get_manufacturer_info(x)
        batts[x] = {"id": x, "serial": serial_numberx, "manuf_info": manuf_info}
      except Exception as e:
        print("no id "+str(x))
        p.clear_buffer()

    if (batts[next(iter(batts))]["serial"] == OPT.pylontech_serial):
        print("serial ok")

        for x in batts.keys():
            batts[x]["hadevice"] = Device(identifiers=batts[x]["serial"],name="Pylontech", display_name="Pylontech "+str(x-1) ,sw_version=str(batts[x]["manuf_info"].SoftwareVersion[0])+"."+str(batts[x]["manuf_info"].SoftwareVersion[1]),model=batts[x]["manuf_info"].DeviceName.decode("utf-8") ,manufacturer=batts[x]["manuf_info"].ManufacturerName.decode("utf-8") )

            print(batts[x]["hadevice"])
            print("battery:"+str(x)+" serial:" + batts[x]["serial"] +"\n")
            batts[x]["sensors"] = {}
            batts[x]["sensors"]["b_volt"] = {}

            for b in range(1, 16):
                batts[x]["sensors"]["b_volt"][b] = Sensor(
                    mqtt_client,
                    "Cell Voltage "+str(b),
                    parent_device=batts[x]["hadevice"],
                    unit_of_measurement="V",
                    topic_parent_level=batts[x]["serial"],
                    )

            batts[x]["sensors"]["b_temp"] = {}

            for b in range(1, 6):
                batts[x]["sensors"]["b_temp"][b] = Sensor(
                    mqtt_client,
                    "Battery Temperature "+str(b),
                    parent_device=batts[x]["hadevice"],
                    unit_of_measurement="°C",
                    topic_parent_level=batts[x]["serial"],
                    )

            batts[x]["sensors"]["tempbms"] = Sensor(
                mqtt_client,
                "BMS Temperature",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="°C",
                topic_parent_level=batts[x]["serial"],
                )

            batts[x]["sensors"]["batcurrent"] = Sensor(
                mqtt_client,
                "Battery Current",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="A",
                topic_parent_level=batts[x]["serial"],
                )

            batts[x]["sensors"]["batvolt"] = Sensor(
                mqtt_client,
                "Battery Voltage",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="V",
                topic_parent_level=batts[x]["serial"],
                )

            batts[x]["sensors"]["batpower"] = Sensor(
                mqtt_client,
                "Battery Power",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="W",
                topic_parent_level=batts[x]["serial"],
                )

            batts[x]["sensors"]["batcycle"] = Sensor(
                mqtt_client,
                "Battery Cycle",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement=" ",
                topic_parent_level=batts[x]["serial"],
                )
            batts[x]["sensors"]["batremcap"] = Sensor(
                mqtt_client,
                "Battery Remaining Capacity",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="Ah",
                topic_parent_level=batts[x]["serial"],
                )
            batts[x]["sensors"]["battotalcap"] = Sensor(
                mqtt_client,
                "Battery Total Capacity",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="Ah",
                topic_parent_level=batts[x]["serial"],
                )
            batts[x]["sensors"]["batsoc"] = Sensor(
                mqtt_client,
                "Battery SoC",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="%",
                device_class="battery",
                topic_parent_level=batts[x]["serial"],
                )


            batts[x]["sensors"]["batdischargelimit"] = Sensor(
                mqtt_client,
                "Battery Discharge Current Limit",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="A",
                topic_parent_level=batts[x]["serial"],
                )

            batts[x]["sensors"]["batchargelimit"] = Sensor(
                mqtt_client,
                "Battery Charge Current Limit",
                parent_device=batts[x]["hadevice"],
                unit_of_measurement="A",
                topic_parent_level=batts[x]["serial"],
                )

        while True:
            for x in batts.keys():

                values = p.get_values_single(batts[x]["id"])
                mgmt_values = p.get_management_info()

                if OPT.debug > 0:
                    print(values)
                    print(mgmt_values)
                
                for b in range(1, 16):
                    batts[x]["sensors"]["b_volt"][b].send(values.CellVoltages[b-1])

                for b in range(1, 6):
                    batts[x]["sensors"]["b_temp"][b].send(values.GroupedCellsTemperatures[0-1])

                batts[x]["sensors"]["tempbms"].send(values.AverageBMSTemperature)

                batts[x]["sensors"]["batcurrent"].send(values.Current)
                batts[x]["sensors"]["batvolt"].send(values.Voltage)
                batts[x]["sensors"]["batpower"].send(values.Power)
                batts[x]["sensors"]["batcycle"].send(values.CycleNumber)
                batts[x]["sensors"]["batremcap"].send(values.RemainingCapacity)
                batts[x]["sensors"]["battotalcap"].send(values.TotalCapacity)
                batts[x]["sensors"]["batsoc"].send(values.StateOfCharge*100)

                batts[x]["sensors"]["batdischargelimit"].send(mgmt_values.DishargeCurrentLimit)
                batts[x]["sensors"]["batchargelimit"].send(mgmt_values.ChargeCurrentLimit)

            time.sleep(10)
