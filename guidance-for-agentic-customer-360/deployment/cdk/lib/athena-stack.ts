import * as cdk from 'aws-cdk-lib';
import * as athena from 'aws-cdk-lib/aws-athena';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as glue from 'aws-cdk-lib/aws-glue';
import { Construct } from 'constructs';

export interface AthenaStackProps extends cdk.StackProps {
  dataLakeBucket: s3.IBucket;
  glueDatabase: glue.CfnDatabase;
}

export class AthenaStack extends cdk.Stack {
  public readonly workgroup: athena.CfnWorkGroup;

  constructor(scope: Construct, id: string, props: AthenaStackProps) {
    super(scope, id, props);

    // Athena Workgroup
    this.workgroup = new athena.CfnWorkGroup(this, 'Workgroup', {
      name: 'cx-analytics-workgroup',
      workGroupConfiguration: {
        resultConfiguration: {
          outputLocation: `s3://${props.dataLakeBucket.bucketName}/athena-results/`,
        },
        enforceWorkGroupConfiguration: true,
        publishCloudWatchMetricsEnabled: true,
      },
    });

    // Customer Health View
    const customerHealthView = new athena.CfnNamedQuery(this, 'CustomerHealthView', {
      database: props.glueDatabase.ref,
      queryString: `
CREATE OR REPLACE VIEW customer_health AS
SELECT 
  customer_id,
  user_id,
  total_revenue,
  avg_satisfaction_score,
  total_cases,
  open_cases,
  total_vehicles,
  total_service_spend,
  total_service_appointments,
  opportunity_count,
  ROUND(
    (COALESCE(avg_satisfaction_score, 50) * 0.25) +
    (CASE WHEN open_cases = 0 THEN 80 ELSE 30 END * 0.20) +
    (CASE WHEN total_vehicles >= 2 THEN 90 ELSE 70 END * 0.15) +
    (CASE WHEN total_service_appointments > 5 THEN 80 ELSE 50 END * 0.30) +
    (100 * 0.10)
  , 2) as health_score,
  CASE 
    WHEN health_score >= 70 THEN 'Healthy'
    WHEN health_score >= 50 THEN 'Needs Attention'
    WHEN health_score >= 30 THEN 'At-Risk'
    ELSE 'Critical'
  END as health_segment
FROM customer_360
      `,
      name: 'customer_health_view',
      workGroup: this.workgroup.name,
    });
    customerHealthView.addDependency(this.workgroup);

    // Churn Prediction View
    const churnPredictionView = new athena.CfnNamedQuery(this, 'ChurnPredictionView', {
      database: props.glueDatabase.ref,
      queryString: `
CREATE OR REPLACE VIEW churn_prediction AS
SELECT 
  customer_id,
  health_score,
  health_segment,
  total_revenue,
  CASE 
    WHEN health_score < 25 THEN 'Critical Risk'
    WHEN health_score < 30 THEN 'High Risk'
    WHEN health_score < 35 THEN 'Medium Risk'
    ELSE 'Low Risk'
  END as churn_risk,
  CASE 
    WHEN health_score < 25 THEN 0.70
    WHEN health_score < 30 THEN 0.45
    WHEN health_score < 35 THEN 0.20
    ELSE 0.05
  END as churn_probability,
  CASE WHEN health_score < 35 THEN 1 ELSE 0 END as churn_indicator,
  total_revenue * CASE 
    WHEN health_score < 25 THEN 0.70
    WHEN health_score < 30 THEN 0.45
    WHEN health_score < 35 THEN 0.20
    ELSE 0.05
  END as expected_loss
FROM customer_health
WHERE health_score < 35
      `,
      name: 'churn_prediction_view',
      workGroup: this.workgroup.name,
    });
    churnPredictionView.addDependency(this.workgroup);

    // CLV Analysis View
    const clvAnalysisView = new athena.CfnNamedQuery(this, 'CLVAnalysisView', {
      database: props.glueDatabase.ref,
      queryString: `
CREATE OR REPLACE VIEW clv_analysis AS
SELECT 
  customer_id,
  total_revenue * 3.5 as actual_clv,
  total_revenue as annual_value,
  total_revenue * 4.2 as predicted_clv_3yr,
  health_score,
  health_segment,
  total_revenue,
  CASE 
    WHEN total_revenue >= 10000 THEN 'B2B Fleet'
    WHEN total_revenue >= 4000 THEN 'B2C Premium'
    WHEN total_revenue >= 2000 THEN 'B2C Standard'
    ELSE 'B2C Entry'
  END as customer_type,
  CASE 
    WHEN total_revenue >= 10000 THEN 'Enterprise'
    WHEN total_revenue >= 4000 THEN 'Premium'
    WHEN total_revenue >= 2000 THEN 'Standard'
    ELSE 'Entry'
  END as value_tier
FROM customer_health
      `,
      name: 'clv_analysis_view',
      workGroup: this.workgroup.name,
    });
    clvAnalysisView.addDependency(this.workgroup);

    // Revenue at Risk View
    const revenueAtRiskView = new athena.CfnNamedQuery(this, 'RevenueAtRiskView', {
      database: props.glueDatabase.ref,
      queryString: `
CREATE OR REPLACE VIEW revenue_at_risk AS
SELECT 
  health_segment,
  COUNT(*) as customer_count,
  SUM(total_revenue) as total_revenue,
  SUM(CASE WHEN health_score < 40 THEN total_revenue ELSE 0 END) as revenue_at_risk,
  ROUND(
    SUM(CASE WHEN health_score < 40 THEN total_revenue ELSE 0 END) * 100.0 / 
    NULLIF(SUM(total_revenue), 0), 2
  ) as pct_at_risk
FROM customer_health
GROUP BY health_segment
      `,
      name: 'revenue_at_risk_view',
      workGroup: this.workgroup.name,
    });
    revenueAtRiskView.addDependency(this.workgroup);

    new cdk.CfnOutput(this, 'AthenaWorkgroup', {
      value: this.workgroup.name!,
      description: 'Athena Workgroup Name',
    });
  }
}
