from enum import StrEnum


class LotStatus(StrEnum):
    RAW = "RAW"
    WIP = "WIP"
    PROCESSED = "PROCESSED"
    HOLD = "HOLD"
    IN_STOCK = "IN_STOCK"
    SHIPPED = "SHIPPED"


class WorkOrderStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    HOLD = "HOLD"


class MachineStatus(StrEnum):
    IDLE = "IDLE"
    RUN = "RUN"
    STOP = "STOP"
    WARNING = "WARNING"


class InspectionResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class Location:
    RAW_WAREHOUSE = "자재창고"
    INSPECTION_WAIT = "검사대기장"
    QUALITY_HOLD = "품질대기"
    FINISHED_WAREHOUSE = "완제품창고"
    SHIPPED = "출하완료"
