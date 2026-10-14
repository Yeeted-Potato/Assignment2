from pydantic import BaseModel, Field, model_validator


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=1)


class CustomerLogin(BaseModel):
    name: str
    email: str


class OrderCreate(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    delivery_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_delivery_details(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be provided together")
        if not self.delivery_address and self.latitude is None:
            raise ValueError("Give a delivery address or allow location")
        return self


class OrderStatusUpdate(BaseModel):
    status: str = Field(min_length=1)


class StaffLogin(BaseModel):
    email: str
    password: str
