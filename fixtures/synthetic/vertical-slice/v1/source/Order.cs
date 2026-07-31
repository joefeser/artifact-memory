namespace SyntheticOrders;

public sealed class Order
{
    public string Status { get; init; } = "pending";
}

public static class OrderStatusReader
{
    public static string Read(Order order)
    {
        return order.Status;
    }
}
